"""Email：變更與驗證信箱、通知設定、忘記密碼。"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from ..forms import EmailChangeForm, NotificationSettingsForm, VerifiedEmailPasswordResetForm
from ..models import ActivityLog, UserProfile
from ..services import activity, notifications
from .common import client_ip


def _require_email():
    if not notifications.enabled():
        raise Http404("尚未設定寄信")


@login_required
@require_POST
def change_email(request):
    _require_email()
    form = EmailChangeForm(request.POST, user=request.user)
    if form.is_valid():
        email = form.cleaned_data["email"]
        notifications.send_verification(request, request.user, email)
        messages.success(request, f"已寄出確認信到 {email}，請在 24 小時內點信中的連結完成變更")
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("storage:security")


@login_required
@require_POST
def notification_settings(request):
    form = NotificationSettingsForm(request.POST, instance=UserProfile.for_user(request.user))
    if form.is_valid():
        form.save()
        messages.success(request, "通知設定已更新")
    return redirect("storage:security")


def verify_email(request, token):
    _require_email()
    try:
        user_id, email = notifications.read_verification(token)
    except signing.SignatureExpired:
        messages.error(request, "確認連結已過期，請重新變更 Email")
        return redirect("storage:security")
    except signing.BadSignature:
        raise Http404("確認連結無效")

    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise Http404("確認連結無效")
    # 同一個信箱只能屬於一個帳號，否則重設密碼時無法確定是哪一個
    taken = (
        get_user_model().objects.filter(email__iexact=email, profile__email_verified=True)
        .exclude(pk=user.pk).exists()
    )
    if taken:
        messages.error(request, "這個 Email 已經被其他帳號使用")
        return redirect("storage:security")

    user.email = email
    user.save(update_fields=["email"])
    profile = UserProfile.for_user(user)
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])
    activity.record(request, ActivityLog.Action.EMAIL_CHANGE, user=user, target=email)
    messages.success(request, f"已確認 Email：{email}")
    return redirect("storage:security" if request.user.is_authenticated else "storage:login")


# --- 忘記密碼 ---------------------------------------------------------------


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "storage/password_reset_form.html"
    email_template_name = "storage/email/password_reset.txt"
    subject_template_name = "storage/email/password_reset_subject.txt"
    form_class = VerifiedEmailPasswordResetForm
    success_url = reverse_lazy("storage:password_reset_done")

    def dispatch(self, request, *args, **kwargs):
        _require_email()
        # 有設定 SITE_URL 時，信中的連結使用固定的網址，不依賴請求的 Host 標頭
        self.extra_email_context = {"site_url": settings.SITE_URL}
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        # 限制同一個 IP 寄出的次數，避免被拿來大量寄信
        key = f"password-resets:{client_ip(request)}"
        count = cache.get(key, 0)
        if count >= settings.PASSWORD_RESETS_PER_IP_PER_HOUR:
            messages.error(request, "重設密碼的要求太頻繁，請稍後再試")
            return render(request, self.template_name, {"form": self.get_form()}, status=429)
        cache.set(key, count + 1, 60 * 60)
        return super().post(request, *args, **kwargs)


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "storage/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "storage/password_reset_confirm.html"
    success_url = reverse_lazy("storage:password_reset_complete")

    def dispatch(self, request, *args, **kwargs):
        _require_email()
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        activity.record(self.request, ActivityLog.Action.PASSWORD_RESET, user=form.user)
        return response


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "storage/password_reset_complete.html"
