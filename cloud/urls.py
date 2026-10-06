from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(f"{settings.SECRET_URL_PREFIX}/admin/", admin.site.urls),
    path(f"{settings.SECRET_URL_PREFIX}/", include("storage.urls")),
]
