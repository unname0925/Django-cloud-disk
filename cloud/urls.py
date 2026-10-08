from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

prefix = settings.SECRET_URL_PREFIX

urlpatterns = [
    # 後台的登入頁改用網站的登入流程，避免繞過登入鎖定與兩步驟驗證
    path(
        f"{prefix}/admin/login/",
        RedirectView.as_view(pattern_name="storage:login", query_string=True),
    ),
    path(f"{prefix}/admin/", admin.site.urls),
    path(f"{prefix}/", include("storage.urls")),
]
