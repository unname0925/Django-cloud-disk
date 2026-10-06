from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..forms import RegisterForm


def _login_failure_key(request):
    return f"login-failures:{request.META.get('REMOTE_ADDR', '')}"


def _redirect_after_login(request):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect(resolve_url(settings.LOGIN_REDIRECT_URL))


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

    failure_key = _login_failure_key(request)
    failures = cache.get(failure_key, 0)
    locked = failures >= settings.LOGIN_MAX_ATTEMPTS
    status = 200

    if request.method == "POST" and not locked:
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            cache.delete(failure_key)
            login(request, form.get_user())
            messages.success(request, "登入成功")
            return _redirect_after_login(request)
        failures += 1
        cache.set(failure_key, failures, settings.LOGIN_LOCKOUT_SECONDS)
        locked = failures >= settings.LOGIN_MAX_ATTEMPTS
    else:
        form = AuthenticationForm(request)

    if locked:
        status = 429
        minutes = settings.LOGIN_LOCKOUT_SECONDS // 60
        messages.error(request, f"登入失敗次數過多，請 {minutes} 分鐘後再試")

    context = {"form": form, "locked": locked, "next": request.GET.get("next", "")}
    return render(request, "storage/login.html", context, status=status)


@require_POST
def logout_view(request):
    logout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)
