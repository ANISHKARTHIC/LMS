from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from .forms import SubmissionForm
from .models import Submission
from .services import evaluate_submission_with_ai
from virtual_lab_eval.experiments.models import Experiment
from virtual_lab_eval.users.models import StudentProfile, get_system_preference


def _draw_image_fit(pdf, image_field, x, y, box_width, box_height):
    if not image_field:
        return False
    try:
        with image_field.open("rb") as image_fp:
            image = ImageReader(image_fp)
            img_width, img_height = image.getSize()
            scale = min(box_width / float(img_width), box_height / float(img_height))
            draw_width = img_width * scale
            draw_height = img_height * scale
            draw_x = x + (box_width - draw_width) / 2
            draw_y = y + (box_height - draw_height) / 2
            pdf.drawImage(
                image,
                draw_x,
                draw_y,
                width=draw_width,
                height=draw_height,
                preserveAspectRatio=True,
                mask="auto",
            )
            return True
    except Exception:
        return False


def _draw_wrapped_text(pdf, text, x, y, max_width, page_height, bottom_margin, font_name="Helvetica", font_size=10, leading=13):
    words = str(text or "-").split()
    if not words:
        words = ["-"]

    lines = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    pdf.setFont(font_name, font_size)
    for line in lines:
        if y <= bottom_margin + leading:
            pdf.showPage()
            y = page_height - (20 * mm)
            pdf.setFont(font_name, font_size)
        pdf.drawString(x, y, line)
        y -= leading
    return y


def submit_experiment(request, experiment_pk):
    experiment = get_object_or_404(Experiment, pk=experiment_pk)
    if request.method == "POST":
        form = SubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.experiment = experiment

            profile, _ = StudentProfile.objects.get_or_create(
                roll_number=submission.roll_number,
                defaults={"full_name": submission.student_name},
            )
            if profile.full_name != submission.student_name:
                profile.full_name = submission.student_name
                profile.save(update_fields=["full_name", "updated_at"])
            submission.student = profile

            ai_result = evaluate_submission_with_ai(
                experiment,
                form.cleaned_data["screenshot"],
                form.cleaned_data.get("explanation", ""),
            )

            submission.ai_score = ai_result["ai_score"]
            submission.explanation_score = ai_result["explanation_score"]
            submission.link_score = ai_result["link_score"]
            submission.ai_feedback = ai_result["ai_feedback"]
            submission.ai_mistakes = ai_result["ai_mistakes"]
            submission.evaluated_at = timezone.now()
            submission.save()

            messages.success(request, "Submission evaluated successfully.")
            return redirect("submissions:submission_result", submission_pk=submission.pk)
        messages.error(request, "Please fix the errors below and submit again.")
    else:
        form = SubmissionForm()
    return render(request, "submissions/submission_form.html", {"form": form, "experiment": experiment})


def submission_result(request, submission_pk):
    submission = get_object_or_404(Submission, pk=submission_pk)
    preference = get_system_preference()
    show_ai_evaluation = preference.show_ai_evaluation_to_students or request.user.is_staff
    return render(
        request,
        "submissions/submission_result.html",
        {
            "submission": submission,
            "show_ai_evaluation": show_ai_evaluation,
        },
    )


def submission_history(request):
    student_name = request.GET.get("name", "").strip()
    roll_number = request.GET.get("roll", "").strip()

    results = Submission.objects.select_related("experiment")
    if roll_number:
        results = results.filter(roll_number__iexact=roll_number)
    else:
        results = results.none()

    if student_name:
        results = results.filter(student_name__icontains=student_name)

    return render(
        request,
        "submissions/submission_history.html",
        {
            "submissions": results,
            "student_name": student_name,
            "roll_number": roll_number,
        },
    )


def download_certificate(request, submission_pk):
    submission = get_object_or_404(Submission, pk=submission_pk)
    if not submission.passed:
        messages.error(request, "Certificate is available only for passed submissions.")
        return redirect("submissions:submission_result", submission_pk=submission.pk)

    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = f'attachment; filename="certificate_{submission.student_name}.pdf"'

    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 28)
    p.drawCentredString(width / 2, height - 60 * mm, "Certificate of Completion")
    p.setFont("Helvetica", 14)
    p.drawCentredString(width / 2, height - 80 * mm, "This certifies that")

    p.setFont("Helvetica-Bold", 22)
    p.drawCentredString(width / 2, height - 95 * mm, submission.student_name)

    p.setFont("Helvetica", 14)
    p.drawCentredString(width / 2, height - 108 * mm, "has successfully passed")
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width / 2, height - 118 * mm, submission.experiment.title)

    p.setFont("Helvetica", 12)
    p.drawCentredString(width / 2, height - 132 * mm, f"Final Score: {submission.final_score}/100")
    p.drawCentredString(
        width / 2,
        height - 140 * mm,
        f"Date: {submission.submitted_at.strftime('%d %b %Y')}",
    )

    p.showPage()
    p.save()

    return response


def download_submission_record_pdf(request, submission_pk):
    submission = get_object_or_404(Submission, pk=submission_pk)
    preference = get_system_preference()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="submission_record_{submission.roll_number}_{submission.pk}.pdf"'
    )

    pdf = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    outer_margin = 14 * mm
    outer_x = outer_margin
    outer_y = outer_margin
    outer_w = width - (2 * outer_margin)
    outer_h = height - (2 * outer_margin)

    content_x = outer_x + (8 * mm)
    content_w = outer_w - (16 * mm)

    footer_text_y = outer_y + (4.2 * mm)
    footer_line_y = outer_y + (10 * mm)
    min_content_y = outer_y + (13 * mm)

    page_no = 0

    def wrap_lines(text: str, max_width: float, font_name: str = "Times-Roman", font_size: int = 11) -> list[str]:
        paragraphs = str(text or "-").splitlines() or ["-"]
        lines: list[str] = []
        for paragraph in paragraphs:
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        return lines

    def draw_center_wrapped(
        text: str,
        center_x: float,
        top_y: float,
        max_width: float,
        font_name: str = "Times-Bold",
        font_size: int = 12,
        leading: float = 5.2 * mm,
    ) -> None:
        lines = wrap_lines(text, max_width, font_name=font_name, font_size=font_size)
        pdf.setFont(font_name, font_size)
        y_pos = top_y
        for line in lines:
            pdf.drawCentredString(center_x, y_pos, line)
            y_pos -= leading

    def draw_page_frame() -> float:
        nonlocal page_no
        page_no += 1

        pdf.setStrokeColor(colors.HexColor("#4B5563"))
        pdf.setLineWidth(1.3)
        pdf.rect(outer_x, outer_y, outer_w, outer_h, stroke=1, fill=0)

        logo_y = outer_y + outer_h - (22 * mm)
        _draw_image_fit(pdf, preference.left_logo, outer_x + (6 * mm), logo_y, 38 * mm, 14 * mm)
        _draw_image_fit(pdf, preference.right_logo, outer_x + outer_w - (44 * mm), logo_y, 38 * mm, 14 * mm)

        pdf.setFillColor(colors.HexColor("#1F2937"))
        pdf.setFont("Times-Roman", 10)
        pdf.drawRightString(outer_x + outer_w - (6 * mm), outer_y + outer_h - (4.5 * mm), f"Page No: {page_no}")

        meta_top = outer_y + outer_h - (27 * mm)
        meta_h = 20 * mm
        left_x = outer_x + (8 * mm)
        left_w = 38 * mm
        gap = 5 * mm
        right_x = left_x + left_w + gap
        right_w = outer_x + outer_w - (8 * mm) - right_x

        pdf.setStrokeColor(colors.HexColor("#4B5563"))
        pdf.setLineWidth(1)
        pdf.rect(left_x, meta_top - meta_h, left_w, meta_h, stroke=1, fill=0)
        pdf.line(left_x, meta_top - (meta_h / 2), left_x + left_w, meta_top - (meta_h / 2))
        split_x = left_x + (left_w * 0.42)
        pdf.line(split_x, meta_top, split_x, meta_top - meta_h)

        pdf.setFont("Times-Bold", 10)
        pdf.setFillColor(colors.HexColor("#111827"))
        pdf.drawString(left_x + (2 * mm), meta_top - (6 * mm), "Ex. No")
        pdf.drawString(left_x + (2 * mm), meta_top - (16 * mm), "Date")

        pdf.setFont("Times-Bold", 11)
        pdf.drawString(split_x + (2 * mm), meta_top - (6 * mm), f"{submission.experiment_id:02d}")
        pdf.setFont("Times-Roman", 10)
        pdf.drawString(split_x + (2 * mm), meta_top - (16 * mm), submission.submitted_at.strftime("%d-%m-%Y"))

        pdf.rect(right_x, meta_top - meta_h, right_w, meta_h, stroke=1, fill=0)
        pdf.setFillColor(colors.HexColor("#111827"))
        draw_center_wrapped(
            submission.experiment.title.upper(),
            right_x + (right_w / 2),
            meta_top - (7 * mm),
            right_w - (4 * mm),
            font_name="Times-Bold",
            font_size=12,
            leading=5 * mm,
        )

        pdf.setStrokeColor(colors.HexColor("#9CA3AF"))
        pdf.line(outer_x + (6 * mm), footer_line_y, outer_x + outer_w - (6 * mm), footer_line_y)
        pdf.setFillColor(colors.HexColor("#1F2937"))
        pdf.setFont("Times-Bold", 10)
        pdf.drawString(outer_x + (8 * mm), footer_text_y, f"Name: {submission.student_name}")
        pdf.drawRightString(outer_x + outer_w - (8 * mm), footer_text_y, f"Roll No: {submission.roll_number}")

        return meta_top - meta_h - (7 * mm)

    y = draw_page_frame()

    def new_page() -> None:
        nonlocal y
        pdf.showPage()
        y = draw_page_frame()

    def ensure_space(required_height: float) -> None:
        nonlocal y
        if y - required_height < min_content_y:
            new_page()

    def draw_section(title: str, text: str) -> None:
        nonlocal y
        ensure_space(14 * mm)
        pdf.setFillColor(colors.HexColor("#111827"))
        pdf.setFont("Times-Bold", 12)
        pdf.drawString(content_x, y, f"{title}:")
        y -= 5 * mm
        pdf.setStrokeColor(colors.HexColor("#D1D5DB"))
        pdf.line(content_x, y, content_x + content_w, y)
        y -= 3.5 * mm

        lines = wrap_lines(text, content_w, font_name="Times-Roman", font_size=11)
        pdf.setFont("Times-Roman", 11)
        pdf.setFillColor(colors.black)
        for line in lines:
            ensure_space(5.5 * mm)
            pdf.drawString(content_x, y, line)
            y -= 4.8 * mm
        y -= 2.5 * mm

    draw_section("AIM", submission.experiment.aim)
    draw_section("PROCEDURE", submission.experiment.procedure)

    ensure_space(78 * mm)
    pdf.setFillColor(colors.HexColor("#111827"))
    pdf.setFont("Times-Bold", 12)
    pdf.drawString(content_x, y, "SCREENSHOT:")
    y -= 5 * mm
    pdf.setStrokeColor(colors.HexColor("#D1D5DB"))
    pdf.line(content_x, y, content_x + content_w, y)
    y -= 3.5 * mm

    screenshot_h = 60 * mm
    if y - screenshot_h < min_content_y:
        new_page()
        pdf.setFillColor(colors.HexColor("#111827"))
        pdf.setFont("Times-Bold", 12)
        pdf.drawString(content_x, y, "SCREENSHOT:")
        y -= 5 * mm
        pdf.setStrokeColor(colors.HexColor("#D1D5DB"))
        pdf.line(content_x, y, content_x + content_w, y)
        y -= 3.5 * mm

    pdf.setStrokeColor(colors.HexColor("#9CA3AF"))
    pdf.roundRect(content_x, y - screenshot_h, content_w, screenshot_h, 4, stroke=1, fill=0)
    if not _draw_image_fit(
        pdf,
        submission.screenshot,
        content_x + (2 * mm),
        y - screenshot_h + (2 * mm),
        content_w - (4 * mm),
        screenshot_h - (4 * mm),
    ):
        pdf.setFont("Times-Roman", 11)
        pdf.setFillColor(colors.HexColor("#6B7280"))
        pdf.drawString(content_x + (4 * mm), y - (screenshot_h / 2), "Screenshot preview unavailable")
    y = y - screenshot_h - (5 * mm)

    if submission.explanation:
        draw_section("EXPLANATION", submission.explanation)

    result_text = (
        f"Expected Result: {submission.experiment.expected_result}\n"
        f"Final Score: {submission.final_score}/100\n"
        f"Status: {'Passed' if submission.passed else 'Failed'}"
    )
    draw_section("RESULT", result_text)

    pdf.save()

    return response


if settings.STUDENT_LOGIN_REQUIRED:
    submit_experiment = login_required(submit_experiment)
    submission_result = login_required(submission_result)
    submission_history = login_required(submission_history)
    download_certificate = login_required(download_certificate)
    download_submission_record_pdf = login_required(download_submission_record_pdf)

