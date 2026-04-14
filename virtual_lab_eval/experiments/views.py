from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render

from .models import Experiment
from virtual_lab_eval.submissions.models import Submission


def experiment_list(request):
    experiments = Experiment.objects.all()
    return render(request, "experiments/experiment_list.html", {"experiments": experiments})


def experiment_detail(request, pk):
    experiment = get_object_or_404(Experiment, pk=pk)
    return render(request, "experiments/experiment_detail.html", {"experiment": experiment})


@staff_member_required
def admin_analytics(request):
    total_submissions = Submission.objects.count()
    passed_submissions = Submission.objects.filter(passed=True).count()
    failed_submissions = total_submissions - passed_submissions
    pass_rate = round((passed_submissions / total_submissions) * 100, 2) if total_submissions else 0

    experiment_stats = (
        Experiment.objects.annotate(
            total=Count("submissions"),
            passed=Count("submissions", filter=Q(submissions__passed=True)),
        )
        .order_by("title")
    )

    return render(
        request,
        "experiments/admin_analytics.html",
        {
            "total_submissions": total_submissions,
            "passed_submissions": passed_submissions,
            "failed_submissions": failed_submissions,
            "pass_rate": pass_rate,
            "experiment_stats": experiment_stats,
        },
    )

