from django.core.management.base import BaseCommand
from django.db.models import Q

from virtual_lab_eval.submissions.models import Submission


class Command(BaseCommand):
    help = "Normalize old submissions impacted by AI provider failures (429/404/model config)."

    def handle(self, *args, **options):
        queryset = Submission.objects.filter(
            Q(ai_feedback__icontains="429")
            | Q(ai_feedback__icontains="404")
            | Q(ai_feedback__icontains="model")
            | Q(ai_feedback__icontains="provider request failed", ai_score=0)
            | Q(ai_mistakes__icontains="rate limit")
            | Q(ai_mistakes__icontains="configuration")
            | Q(ai_mistakes__icontains="could not evaluate screenshot", ai_score=0)
        )
        updated = 0

        for submission in queryset:
            changed = False
            if submission.ai_score == 0:
                submission.ai_score = 50
                changed = True
            feedback_lower = (submission.ai_feedback or "").lower()
            if ("rate limit" not in feedback_lower) and ("provisional" not in feedback_lower):
                submission.ai_feedback = (
                    "AI provider was unavailable during evaluation. "
                    "A provisional score was applied. Re-evaluate later for final AI score."
                )
                changed = True
            mistakes_lower = (submission.ai_mistakes or "").lower()
            if ("rate limit" not in mistakes_lower) and ("configuration" not in mistakes_lower):
                submission.ai_mistakes = "AI evaluation postponed due to temporary provider issue."
                changed = True

            if changed:
                submission.save()
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} submissions with provider-error fallbacks."))
