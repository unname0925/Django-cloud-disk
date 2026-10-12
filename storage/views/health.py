from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .. import health


@never_cache
@require_GET
def healthz(request):
    """給 Docker 或監控服務使用的健康檢查。有錯誤時回傳 503。"""
    overall, results = health.run_checks()
    status = 503 if overall == health.ERROR else 200
    return JsonResponse({"status": overall, "checks": results},
                        status=status, json_dumps_params={"ensure_ascii": False})
