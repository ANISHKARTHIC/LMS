from django.contrib import admin
from .models import Experiment


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = ("title", "pass_marks", "updated_at")
    search_fields = ("title", "aim", "procedure")
    list_filter = ("pass_marks",)

