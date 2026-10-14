"""PWA：manifest、Service Worker 與離線頁面。"""
from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control


def _scope():
    return f"/{settings.SECRET_URL_PREFIX}/"


@cache_control(max_age=3600)
def manifest(request):
    data = {
        "name": "Cloud Drive",
        "short_name": "Cloud Drive",
        "description": "個人雲端硬碟",
        "lang": "zh-Hant",
        "start_url": reverse("storage:browse"),
        "scope": _scope(),
        "display": "standalone",
        "background_color": "#f6f7f9",
        "theme_color": "#2563eb",
        "icons": [
            {"src": static("storage/icons/icon-192.png"), "sizes": "192x192",
             "type": "image/png"},
            {"src": static("storage/icons/icon-512.png"), "sizes": "512x512",
             "type": "image/png"},
            {"src": static("storage/icons/icon-maskable-512.png"), "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }
    response = JsonResponse(data, json_dumps_params={"ensure_ascii": False})
    response["Content-Type"] = "application/manifest+json"
    return response


@cache_control(no_cache=True)
def service_worker(request):
    """Service Worker 必須放在 /<前綴>/ 底下，作用範圍才能涵蓋整個網站。"""
    path = finders.find("storage/sw.js")
    if path is None:
        raise Http404
    return FileResponse(open(path, "rb"), content_type="text/javascript")


def offline(request):
    # 會被 Service Worker 快取起來，不能包含任何使用者的資料
    return render(request, "storage/offline.html")
