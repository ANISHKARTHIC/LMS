from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("admin-panel/", views.admin_dashboard, name="admin_dashboard"),
]
