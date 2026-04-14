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
    margin = 16 * mm
    bottom_margin = 16 * mm
    content_width = width - (2 * margin)

    pdf.setStrokeColor(colors.HexColor("#CBD5E1"))
    pdf.setLineWidth(1)
    pdf.roundRect(
        margin - 4,
        bottom_margin - 4,
        width - (2 * margin) + 8,
        height - (2 * bottom_margin) + 8,
        8,
        stroke=1,
        fill=0,
    )

    logo_y = height - (35 * mm)
    _draw_image_fit(pdf, preference.left_logo, margin, logo_y, 38 * mm, 20 * mm)
    _draw_image_fit(pdf, preference.right_logo, width - margin - (38 * mm), logo_y, 38 * mm, 20 * mm)

    pdf.setFillColor(colors.HexColor("#0B3D5E"))
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(width / 2, height - (28 * mm), "Virtual Lab Record")
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(colors.HexColor("#334155"))
    pdf.drawCentredString(width / 2, height - (34 * mm), "Generated after submission")

    y = height - (46 * mm)
    pdf.setStrokeColor(colors.HexColor("#E5E7EB"))
    pdf.line(margin, y, width - margin, y)
    y -= 9 * mm

    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin, y, "Record Information")
    y -= 7 * mm

    detail_lines = [
        f"Student Name: {submission.student_name}",
        f"Roll Number: {submission.roll_number}",
        f"Experiment: {submission.experiment.title}",
        f"Submitted At: {submission.submitted_at.strftime('%d %b %Y, %H:%M')}",
        f"Tinkercad Link: {submission.tinkercad_link}",
    ]

    for line in detail_lines:
        y = _draw_wrapped_text(
            pdf,
            line,
            margin,
            y,
            content_width,
            height,
            bottom_margin,
            font_name="Helvetica",
            font_size=10,
            leading=12,
        )
        y -= 1.5 * mm

    y -= 3 * mm
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin, y, "Aim")
    y -= 6 * mm
    y = _draw_wrapped_text(
        pdf,
        submission.experiment.aim,
        margin,
        y,
        content_width,
        height,
        bottom_margin,
        font_name="Helvetica",
        font_size=10,
        leading=12,
    )

    y -= 4 * mm
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin, y, "Procedure")
    y -= 6 * mm
    y = _draw_wrapped_text(
        pdf,
        submission.experiment.procedure,
        margin,
        y,
        content_width,
        height,
        bottom_margin,
        font_name="Helvetica",
        font_size=10,
        leading=12,
    )

    y -= 4 * mm
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin, y, "Screenshot")
    y -= 6 * mm

    image_box_height = 60 * mm
    image_box_width = content_width
    if y - image_box_height < bottom_margin + 20 * mm:
        pdf.showPage()
        y = height - (22 * mm)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(margin, y, "Screenshot")
        y -= 6 * mm

    pdf.setStrokeColor(colors.HexColor("#CBD5E1"))
    pdf.roundRect(margin, y - image_box_height, image_box_width, image_box_height, 4, stroke=1, fill=0)
    if not _draw_image_fit(
        pdf,
        submission.screenshot,
        margin + 2 * mm,
        y - image_box_height + 2 * mm,
        image_box_width - 4 * mm,
        image_box_height - 4 * mm,
    ):
        pdf.setFont("Helvetica", 10)
        pdf.setFillColor(colors.HexColor("#6B7280"))
        pdf.drawString(margin + 4 * mm, y - (image_box_height / 2), "Screenshot preview unavailable")

    y = y - image_box_height - (6 * mm)

    if submission.explanation:
        if y < bottom_margin + (28 * mm):
            pdf.showPage()
            y = height - (22 * mm)
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(margin, y, "Explanation")
        y -= 6 * mm
        y = _draw_wrapped_text(
            pdf,
            submission.explanation,
            margin,
            y,
            content_width,
            height,
            bottom_margin,
            font_name="Helvetica",
            font_size=10,
            leading=12,
        )
        y -= 4 * mm

    if y < bottom_margin + (22 * mm):
        pdf.showPage()
        y = height - (22 * mm)

    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin, y, "Result")
    y -= 6 * mm

    result_lines = [
        f"Final Score: {submission.final_score}/100",
        f"Status: {'Passed' if submission.passed else 'Failed'}",
    ]
    for line in result_lines:
        y = _draw_wrapped_text(
            pdf,
            line,
            margin,
            y,
            content_width,
            height,
            bottom_margin,
            font_name="Helvetica",
            font_size=10,
            leading=12,
        )

    y -= 2 * mm
    pdf.setFillColor(colors.HexColor("#64748B"))
    pdf.setFont("Helvetica-Oblique", 9)
    pdf.drawString(
        margin,
        max(bottom_margin, y - 2 * mm),
        "Generated record. This PDF is generated on request and is not stored as a separate file.",
    )

    pdf.showPage()
    pdf.save()

    return response


if settings.STUDENT_LOGIN_REQUIRED:
    submit_experiment = login_required(submit_experiment)
    submission_result = login_required(submission_result)
    submission_history = login_required(submission_history)
    download_certificate = login_required(download_certificate)
    download_submission_record_pdf = login_required(download_submission_record_pdf)

