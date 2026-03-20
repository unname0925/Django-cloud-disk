from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import include, path


def root_redirect(request):
    return HttpResponseRedirect("/login/")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("storage.urls")),
    path("", root_redirect),
]