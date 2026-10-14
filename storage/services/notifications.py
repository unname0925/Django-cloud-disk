"""Email 通知與信箱驗證。

沒有設定寄信（EMAIL_ENABLED=False）時，所有寄信功能都不會執行。
"""
import logging

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from ..models import ActivityLog, UserProfile

logger = logging.getLogger(__name__)

VERIFY_SALT = "storage.email-verification"
VERIFY_MAX_AGE = 24 * 60 * 60
SHARE_NOTIFY_INTERVAL = 60 * 60


def enabled():
    return settings.EMAIL_ENABLED


def site_url(request=None):
    if settings.SITE_URL:
        return settings.SITE_URL
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    return ""


def _deliver(to, subject, template, context):
    body = render_to_string(f"storage/email/{template}.txt", context)

    def send():
        try:
            send_mail(f"[Cloud Drive] {subject}", body, None, [to])
        except Exception:  # noqa: BLE001 - 寄信失敗不能影響使用者的操作
            logger.exception("寄送 Email 失敗：%s", subject)

    # 交易確定提交後才寄，避免資料回滾了信卻已經寄出
    transaction.on_commit(send)


def notify(user, subject, template, context=None, request=None):
    """寄通知給已驗證信箱的使用者，回傳是否寄出。"""
    if not enabled() or not user.email:
        return False
    if not UserProfile.for_user(user).email_verified:
        return False
    _deliver(user.email, subject, template, {
        **(context or {}), "user": user, "site_url": site_url(request),
        "now": timezone.localtime(),
    })
    return True


# --- 各種通知 ---------------------------------------------------------------


def notify_new_login(request, user, log):
    """這組 IP 與裝置第一次登入時通知。第一次使用（沒有任何登入紀錄）時不通知。"""
    profile = UserProfile.for_user(user)
    if not profile.notify_new_login:
        return False
    previous = ActivityLog.objects.filter(user=user, action=ActivityLog.Action.LOGIN).exclude(
        pk=log.pk
    )
    if not previous.exists():
        return False
    if previous.filter(ip=log.ip, user_agent=log.user_agent).exists():
        return False
    return notify(user, "新裝置登入", "new_login", {
        "log": log, "security_url": site_url(request) + reverse("storage:security"),
    }, request)


def notify_share_download(request, link, log):
    """分享連結被下載時通知分享者；同一個連結一小時內最多通知一次。"""
    owner = link.owner
    if not UserProfile.for_user(owner).notify_share_download:
        return False
    key = f"share-download-notified:{link.pk}"
    if not cache.add(key, True, SHARE_NOTIFY_INTERVAL):
        return False
    return notify(owner, f"「{link.target_name}」的分享連結被下載", "share_download", {
        "link": link, "log": log,
        "shares_url": site_url(request) + reverse("storage:my_shares"),
    }, request)


def check_quota(request, user):
    """用量超過 QUOTA_WARNING_PERCENT 時寄一次警告；降到門檻減 10% 以下才會重新提醒。"""
    profile = UserProfile.for_user(user)
    quota = profile.quota
    percent = profile.used_bytes * 100 / quota if quota else 100
    threshold = settings.QUOTA_WARNING_PERCENT
    if percent >= threshold and not profile.quota_warning_sent:
        profile.quota_warning_sent = True
        profile.save(update_fields=["quota_warning_sent"])
        if profile.notify_quota:
            return notify(user, "容量快用完了", "quota", {
                "percent": round(percent), "profile": profile,
                "trash_url": site_url(request) + reverse("storage:trash"),
                "duplicates_url": site_url(request) + reverse("storage:duplicates"),
            }, request)
    elif percent < threshold - 10 and profile.quota_warning_sent:
        profile.quota_warning_sent = False
        profile.save(update_fields=["quota_warning_sent"])
    return False


# --- 信箱驗證 ---------------------------------------------------------------


def send_verification(request, user, email):
    """寄確認信到新的信箱；點連結後才會變更帳號的 Email。"""
    token = signing.dumps({"user": user.pk, "email": email}, salt=VERIFY_SALT)
    link = site_url(request) + reverse("storage:verify_email", args=[token])
    _deliver(email, "請確認你的 Email", "verify_email",
             {"user": user, "link": link, "hours": VERIFY_MAX_AGE // 3600})


def read_verification(token):
    """回傳 (使用者 id, email)；連結過期或被竄改時丟出 signing.BadSignature。"""
    data = signing.loads(token, salt=VERIFY_SALT, max_age=VERIFY_MAX_AGE)
    return data["user"], data["email"]
