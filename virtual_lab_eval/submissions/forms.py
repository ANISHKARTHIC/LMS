from django import forms
from django.conf import settings
from urllib.parse import urlparse

from .models import Submission


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ["student_name", "roll_number", "tinkercad_link", "screenshot", "explanation"]
        widgets = {
            "student_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Enter full name"}
            ),
            "roll_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Enter roll number"}
            ),
            "tinkercad_link": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://www.tinkercad.com/...",
                }
            ),
            "screenshot": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "explanation": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Optional: explain your design choices",
                }
            ),
        }

    def clean_tinkercad_link(self):
        url = self.cleaned_data["tinkercad_link"].strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise forms.ValidationError("Please provide a valid URL.")

        if "tinkercad.com" not in parsed.netloc.lower():
            raise forms.ValidationError("Please submit a valid Tinkercad URL.")
        return url

    def clean_screenshot(self):
        screenshot = self.cleaned_data.get("screenshot")
        if not screenshot:
            raise forms.ValidationError("Screenshot is required.")

        content_type = getattr(screenshot, "content_type", "")
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise forms.ValidationError("Allowed image formats: PNG, JPG/JPEG, WEBP.")

        max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if screenshot.size > max_size:
            raise forms.ValidationError(
                f"Image size must be <= {settings.MAX_UPLOAD_SIZE_MB} MB."
            )
        return screenshot

