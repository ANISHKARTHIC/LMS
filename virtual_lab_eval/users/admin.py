from django.contrib import admin

from .models import StudentProfile, SystemPreference


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("roll_number", "full_name", "updated_at")
    search_fields = ("roll_number", "full_name")


@admin.register(SystemPreference)
class SystemPreferenceAdmin(admin.ModelAdmin):
    list_display = ("id", "show_ai_evaluation_to_students", "updated_at")
    fields = ("show_ai_evaluation_to_students", "left_logo", "right_logo", "updated_at")
    readonly_fields = ("updated_at",)

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        # Keep this as a singleton-style settings row.
        return not SystemPreference.objects.exists()

