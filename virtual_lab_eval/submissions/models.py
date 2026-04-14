from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator

from virtual_lab_eval.experiments.models import Experiment
from virtual_lab_eval.users.models import StudentProfile


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class Submission(models.Model):
    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(
        StudentProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submissions",
    )
    student_name = models.CharField(max_length=100)
    roll_number = models.CharField(max_length=50)
    tinkercad_link = models.URLField()
    screenshot = models.ImageField(upload_to="screenshots/%Y/%m/%d/")
    explanation = models.TextField(blank=True, null=True)

    ai_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    explanation_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    link_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    admin_review_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    override_final_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    ai_feedback = models.TextField(blank=True)
    ai_mistakes = models.TextField(blank=True)
    final_score = models.PositiveSmallIntegerField(default=0)
    passed = models.BooleanField(default=False)
    approval_status = models.CharField(
        max_length=12,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )

    evaluated_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]

    def calculate_weighted_score(self) -> int:
        weighted = (
            (self.ai_score * 0.50)
            + (self.link_score * 0.20)
            + (self.explanation_score * 0.10)
            + (self.admin_review_score * 0.20)
        )
        return int(round(weighted))

    def apply_pass_state(self) -> None:
        auto_score = self.calculate_weighted_score()
        self.final_score = self.override_final_score if self.override_final_score is not None else auto_score

        pass_by_score = self.final_score >= self.experiment.pass_marks
        if self.approval_status == ApprovalStatus.APPROVED:
            self.passed = True
        elif self.approval_status == ApprovalStatus.REJECTED:
            self.passed = False
        else:
            self.passed = pass_by_score

    def save(self, *args, **kwargs):
        if self.experiment_id:
            self.apply_pass_state()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Submission for {self.experiment.title} by {self.student_name}"

