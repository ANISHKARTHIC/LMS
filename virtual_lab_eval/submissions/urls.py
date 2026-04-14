from django.urls import path
from . import views

app_name = "submissions"

urlpatterns = [
    path("experiment/<int:experiment_pk>/submit/", views.submit_experiment, name="submit_experiment"),
    path("<int:submission_pk>/result/", views.submission_result, name="submission_result"),
    path("<int:submission_pk>/certificate/", views.download_certificate, name="download_certificate"),
    path("history/", views.submission_history, name="submission_history"),
]

