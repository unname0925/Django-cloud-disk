from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import include, path
from django.conf import settings


urlpatterns = [
    path(f"{settings.SECRET_URL_PREFIX}/admin/", admin.site.urls),
    path(f"{settings.SECRET_URL_PREFIX}/", include("storage.urls")),
]