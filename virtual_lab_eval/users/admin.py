from django.contrib import admin

from .models import StudentProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("roll_number", "full_name", "updated_at")
    search_fields = ("roll_number", "full_name")
