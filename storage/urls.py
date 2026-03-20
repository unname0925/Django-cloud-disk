from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboardF, name="dashboard"),
    path("register/", views.registerF, name="register"),
    path("login/", views.loginF, name="login"),
    path("logout/", views.logoutF, name="logout"),
    path("upload/", views.uploadF, name="upload"),
    path("file/<int:file_id>/download/", views.downloadF, name="download"),
    path("file/<int:file_id>/delete/", views.deleteF, name="delete"),
]