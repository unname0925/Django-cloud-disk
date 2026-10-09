"""活動紀錄。"""
import ipaddress
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..models import ActivityLog

Action = ActivityLog.Action
LOGIN_EVENTS = (Action.LOGIN, Action.LOGIN_FAILED, Action.TWO_FACTOR_FAILED)


def _ip(request):
    # 延遲匯入，避免 services 依賴 views 造成循環匯入
    from ..views.common import client_ip

    value = client_ip(request)
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def record(request, action, *, user=None, target="", username=""):
    if user is None and request.user.is_authenticated:
        user = request.user
    return ActivityLog.objects.create(
        user=user,
        username=(user.get_username() if user else username)[:150],
        action=action,
        target=str(target)[:255],
        ip=_ip(request),
        user_agent=request.headers.get("User-Agent", "")[:255],
    )


def log_upload(request, result):
    if result.outcome == "created":
        record(request, Action.UPLOAD, target=result.stored.original_name)
    elif result.outcome == "updated":
        record(request, Action.UPDATE, target=result.stored.original_name)


def login_summary(user, current_log):
    """登入時的提醒：上次登入的時間與 IP，以及之後失敗的登入嘗試次數。"""
    previous = (
        ActivityLog.objects.filter(user=user, action=Action.LOGIN)
        .exclude(pk=current_log.pk)
        .first()
    )
    failures = ActivityLog.objects.filter(
        user=user, action__in=(Action.LOGIN_FAILED, Action.TWO_FACTOR_FAILED),
    )
    if previous is not None:
        failures = failures.filter(created_time__gt=previous.created_time)
    return previous, failures.count()


def recent_logins(user, limit=10):
    return ActivityLog.objects.filter(user=user, action__in=LOGIN_EVENTS)[:limit]


def purge_old():
    cutoff = timezone.now() - timedelta(days=settings.ACTIVITY_LOG_RETENTION_DAYS)
    deleted, _ = ActivityLog.objects.filter(created_time__lt=cutoff).delete()
    return deleted
