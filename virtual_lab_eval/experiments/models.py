from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator


class Experiment(models.Model):
    title = models.CharField(max_length=200)
    aim = models.TextField()
    procedure = models.TextField()
    expected_result = models.TextField()
    pass_marks = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

