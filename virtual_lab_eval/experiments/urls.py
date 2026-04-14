from django.urls import path
from . import views

app_name = "experiments"

urlpatterns = [
    path("", views.experiment_list, name="experiment_list"),
    path("experiment/<int:pk>/", views.experiment_detail, name="experiment_detail"),
    path("admin-analytics/", views.admin_analytics, name="admin_analytics"),
]

