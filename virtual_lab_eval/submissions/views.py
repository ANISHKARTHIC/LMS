from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .forms import SubmissionForm
from .models import Submission
from .services import evaluate_submission_with_ai
from virtual_lab_eval.experiments.models import Experiment
from virtual_lab_eval.users.models import StudentProfile


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
    return render(request, "submissions/submission_result.html", {"submission": submission})


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


if settings.STUDENT_LOGIN_REQUIRED:
    submit_experiment = login_required(submit_experiment)
    submission_result = login_required(submission_result)
    submission_history = login_required(submission_history)
    download_certificate = login_required(download_certificate)

