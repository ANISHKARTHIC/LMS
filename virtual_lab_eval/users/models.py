from django.db import models


class StudentProfile(models.Model):
    full_name = models.CharField(max_length=120)
    roll_number = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["roll_number"]

    def __str__(self):
        return f"{self.roll_number} - {self.full_name}"


class SystemPreference(models.Model):
    show_ai_evaluation_to_students = models.BooleanField(
        default=False,
        help_text="If enabled, students can see AI score/feedback/mistakes on result pages and record PDF.",
    )
    left_logo = models.ImageField(upload_to="branding/", blank=True, null=True)
    right_logo = models.ImageField(upload_to="branding/", blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "System Preference"
        verbose_name_plural = "System Preferences"

    def save(self, *args, **kwargs):
        # Keep a single editable row for global portal configuration.
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return "Portal Settings"


def get_system_preference() -> SystemPreference:
    pref, _ = SystemPreference.objects.get_or_create(pk=1)
    return pref
