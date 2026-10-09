import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render, resolve_url
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..forms import DisableTwoFactorForm, RegisterForm, TwoFactorCodeForm
from ..models import ActivityLog
from ..services import activity, twofactor
from .common import client_ip

# 輸入密碼後，必須在這段時間內完成兩步驟驗證
PENDING_LOGIN_SECONDS = 5 * 60
PENDING_LOGIN_KEY = "pending_2fa_login"
SETUP_SECRET_KEY = "pending_2fa_secret"


def _failure_key(request):
    return f"login-failures:{client_ip(request)}"


def _failures(request):
    return cache.get(_failure_key(request), 0)


def _record_failure(request):
    failures = _failures(request) + 1
    cache.set(_failure_key(request), failures, settings.LOGIN_LOCKOUT_SECONDS)
    return failures


def _is_locked(request):
    return _failures(request) >= settings.LOGIN_MAX_ATTEMPTS


def _lockout_message(request):
    minutes = settings.LOGIN_LOCKOUT_SECONDS // 60
    messages.error(request, f"登入失敗次數過多，請 {minutes} 分鐘後再試")


def _safe_redirect(request, next_url):
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect(resolve_url(settings.LOGIN_REDIRECT_URL))


def _complete_login(request, user, backend, next_url):
    cache.delete(_failure_key(request))
    login(request, user, backend=backend)
    log = activity.record(request, ActivityLog.Action.LOGIN, user=user)
    previous, failures = activity.login_summary(user, log)
    messages.success(request, "登入成功")
    if previous is not None:
        when = timezone.localtime(previous.created_time).strftime("%Y-%m-%d %H:%M")
        source = f"{previous.ip or '未知 IP'}（{previous.device or '未知裝置'}）"
        messages.info(request, f"上次登入：{when}，來自 {source}")
    if failures:
        messages.warning(
            request, f"自上次登入以來有 {failures} 次失敗的登入嘗試，若不是你本人，請考慮變更密碼"
        )
    return _safe_redirect(request, next_url)


def _log_login_failure(request, action, username):
    user = get_user_model().objects.filter(username=username).first()
    activity.record(request, action, user=user, username=username)


def register(request):
    if not settings.ALLOW_REGISTRATION:
        raise Http404("目前未開放註冊")
    if request.user.is_authenticated:
        return redirect("storage:browse")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "註冊成功")
            return redirect("storage:browse")
    else:
        form = RegisterForm()

    return render(request, "storage/register.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("storage:browse")

    next_url = request.POST.get("next") or request.GET.get("next", "")
    locked = _is_locked(request)

    if request.method == "POST" and not locked:
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not twofactor.is_enabled(user):
                return _complete_login(request, user, user.backend, next_url)
            # 密碼正確，但還要輸入驗證碼才算登入
            request.session[PENDING_LOGIN_KEY] = {
                "user_id": user.pk,
                "backend": user.backend,
                "next": next_url,
                "started": time.time(),
            }
            return redirect("storage:login_verify")
        _log_login_failure(request, ActivityLog.Action.LOGIN_FAILED,
                           request.POST.get("username", ""))
        locked = _record_failure(request) >= settings.LOGIN_MAX_ATTEMPTS
    else:
        form = AuthenticationForm(request)

    if locked:
        _lockout_message(request)

    context = {"form": form, "locked": locked, "next": next_url}
    return render(request, "storage/login.html", context, status=429 if locked else 200)


def login_verify(request):
    pending = request.session.get(PENDING_LOGIN_KEY)
    if not pending or time.time() - pending["started"] > PENDING_LOGIN_SECONDS:
        request.session.pop(PENDING_LOGIN_KEY, None)
        messages.error(request, "驗證逾時，請重新登入")
        return redirect("storage:login")

    user = get_user_model().objects.filter(pk=pending["user_id"], is_active=True).first()
    if user is None:
        request.session.pop(PENDING_LOGIN_KEY, None)
        return redirect("storage:login")

    locked = _is_locked(request)
    form = TwoFactorCodeForm(request.POST or None)
    if request.method == "POST" and not locked:
        if form.is_valid() and twofactor.verify(user, form.cleaned_data["code"]):
            request.session.pop(PENDING_LOGIN_KEY)
            return _complete_login(request, user, pending["backend"], pending["next"])
        form.add_error("code", "驗證碼不正確")
        activity.record(request, ActivityLog.Action.TWO_FACTOR_FAILED, user=user)
        locked = _record_failure(request) >= settings.LOGIN_MAX_ATTEMPTS

    if locked:
        # 鎖定後必須重新輸入密碼
        request.session.pop(PENDING_LOGIN_KEY, None)
        _lockout_message(request)
        return render(request, "storage/login.html",
                      {"form": AuthenticationForm(request), "locked": True}, status=429)

    return render(request, "storage/login_verify.html", {"form": form})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        activity.record(request, ActivityLog.Action.LOGOUT)
    logout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)


# --- 帳號安全 ---------------------------------------------------------------


@login_required
def security(request):
    password_form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and password_form.is_valid():
        password_form.save()
        activity.record(request, ActivityLog.Action.PASSWORD_CHANGE)
        # 變更密碼後讓目前的登入保持有效，其他裝置會被登出
        update_session_auth_hash(request, password_form.user)
        messages.success(request, "密碼已變更")
        return redirect("storage:security")

    context = {
        "password_form": password_form,
        "two_factor_enabled": twofactor.is_enabled(request.user),
        "recovery_remaining": twofactor.remaining_recovery_codes(request.user),
        "disable_form": DisableTwoFactorForm(user=request.user),
        "regenerate_form": TwoFactorCodeForm(),
        "recent_logins": activity.recent_logins(request.user),
    }
    return render(request, "storage/security.html", context)


@login_required
def two_factor_setup(request):
    if twofactor.is_enabled(request.user):
        return redirect("storage:security")

    # 確認之前先把金鑰放在 session，避免重新整理頁面就換一組
    secret = request.session.get(SETUP_SECRET_KEY)
    if not secret:
        secret = request.session[SETUP_SECRET_KEY] = twofactor.generate_secret()

    form = TwoFactorCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        step = twofactor.match_step(secret, form.cleaned_data["code"])
        if step is not None:
            codes = twofactor.enable(request.user, secret, step)
            activity.record(request, ActivityLog.Action.TWO_FACTOR_ENABLE)
            del request.session[SETUP_SECRET_KEY]
            messages.success(request, "已啟用兩步驟驗證")
            return render(request, "storage/recovery_codes.html", {"codes": codes})
        form.add_error("code", "驗證碼不正確，請確認手機時間正確後再試一次")

    uri = twofactor.provisioning_uri(secret, request.user.get_username())
    context = {
        "form": form,
        "secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)),
        "qr_svg": twofactor.qr_code_svg(uri),
    }
    return render(request, "storage/two_factor_setup.html", context)


@login_required
@require_POST
def two_factor_disable(request):
    if _is_locked(request):
        _lockout_message(request)
        return redirect("storage:security")
    form = DisableTwoFactorForm(request.POST, user=request.user)
    if form.is_valid() and twofactor.verify(request.user, form.cleaned_data["code"]):
        twofactor.disable(request.user)
        activity.record(request, ActivityLog.Action.TWO_FACTOR_DISABLE)
        messages.success(request, "已停用兩步驟驗證")
    else:
        _record_failure(request)
        messages.error(request, "密碼或驗證碼不正確，兩步驟驗證仍然啟用中")
    return redirect("storage:security")


@login_required
@require_POST
def recovery_codes_regenerate(request):
    if _is_locked(request):
        _lockout_message(request)
        return redirect("storage:security")
    form = TwoFactorCodeForm(request.POST)
    if form.is_valid() and twofactor.verify(request.user, form.cleaned_data["code"]):
        codes = twofactor.generate_recovery_codes(request.user)
        activity.record(request, ActivityLog.Action.RECOVERY_CODES)
        messages.success(request, "已產生新的備用碼，舊的備用碼全部作廢")
        return render(request, "storage/recovery_codes.html", {"codes": codes})
    _record_failure(request)
    messages.error(request, "驗證碼不正確")
    return redirect("storage:security")


@login_required
def activity_log(request):
    paginator = Paginator(ActivityLog.objects.filter(user=request.user), 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "storage/activity.html", {"page": page})
