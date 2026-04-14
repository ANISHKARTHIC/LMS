from django.contrib import admin
from django.utils import timezone

from .models import ApprovalStatus, Submission
from .services import evaluate_submission_with_ai


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "experiment",
        "student_name",
        "roll_number",
        "ai_score",
        "explanation_score",
        "admin_review_score",
        "final_score",
        "passed",
        "approval_status",
        "submitted_at",
    )
    list_filter = ("experiment", "passed", "approval_status", "submitted_at")
    search_fields = ("student_name", "roll_number", "experiment__title")
    readonly_fields = (
        "submitted_at",
        "updated_at",
        "evaluated_at",
        "ai_score",
        "explanation_score",
        "link_score",
        "ai_feedback",
        "ai_mistakes",
        "final_score",
    )
    fields = (
        "experiment",
        "student",
        "student_name",
        "roll_number",
        "tinkercad_link",
        "screenshot",
        "explanation",
        "ai_score",
        "explanation_score",
        "link_score",
        "admin_review_score",
        "override_final_score",
        "final_score",
        "approval_status",
        "passed",
        "ai_feedback",
        "ai_mistakes",
        "submitted_at",
        "evaluated_at",
        "updated_at",
    )
    actions = ["approve_submissions", "reject_submissions", "mark_pending", "re_evaluate_ai"]

    def approve_submissions(self, request, queryset):
        for submission in queryset:
            submission.approval_status = ApprovalStatus.APPROVED
            submission.save()

    approve_submissions.short_description = "Approve selected submissions"

    def reject_submissions(self, request, queryset):
        for submission in queryset:
            submission.approval_status = ApprovalStatus.REJECTED
            submission.save()

    reject_submissions.short_description = "Reject selected submissions"

    def mark_pending(self, request, queryset):
        for submission in queryset:
            submission.approval_status = ApprovalStatus.PENDING
            submission.save()

    mark_pending.short_description = "Reset selected submissions to pending"

    def re_evaluate_ai(self, request, queryset):
        updated_count = 0
        skipped_count = 0

        for submission in queryset:
            if not submission.screenshot:
                skipped_count += 1
                continue

            try:
                with submission.screenshot.open("rb") as screenshot_file:
                    ai_result = evaluate_submission_with_ai(
                        submission.experiment,
                        screenshot_file,
                        submission.explanation or "",
                    )
                submission.ai_score = ai_result["ai_score"]
                submission.explanation_score = ai_result["explanation_score"]
                submission.link_score = ai_result["link_score"]
                submission.ai_feedback = ai_result["ai_feedback"]
                submission.ai_mistakes = ai_result["ai_mistakes"]
                submission.evaluated_at = timezone.now()
                submission.save()
                updated_count += 1
            except Exception:
                skipped_count += 1

        self.message_user(
            request,
            f"Re-evaluated {updated_count} submissions. Skipped {skipped_count}.",
        )

    re_evaluate_ai.short_description = "Re-evaluate selected submissions with AI"

