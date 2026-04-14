from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.shortcuts import render

from virtual_lab_eval.experiments.models import Experiment
from virtual_lab_eval.submissions.models import ApprovalStatus, Submission


@staff_member_required(login_url="/admin/login/")
def admin_dashboard(request):
    total_experiments = Experiment.objects.count()
    total_submissions = Submission.objects.count()
    passed_submissions = Submission.objects.filter(passed=True).count()
    failed_submissions = total_submissions - passed_submissions
    pending_reviews = Submission.objects.filter(approval_status=ApprovalStatus.PENDING).count()
    pass_rate = round((passed_submissions / total_submissions) * 100, 2) if total_submissions else 0

    recent_submissions = (
        Submission.objects.select_related("experiment")
        .order_by("-submitted_at")[:8]
    )
    top_experiments = (
        Experiment.objects.annotate(submission_count=Count("submissions"))
        .order_by("-submission_count", "title")[:6]
    )

    return render(
        request,
        "users/admin_dashboard.html",
        {
            "total_experiments": total_experiments,
            "total_submissions": total_submissions,
            "passed_submissions": passed_submissions,
            "failed_submissions": failed_submissions,
            "pending_reviews": pending_reviews,
            "pass_rate": pass_rate,
            "recent_submissions": recent_submissions,
            "top_experiments": top_experiments,
        },
    )
