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
