from django.conf import settings

from .health import configuration_warnings


def site_settings(request):
    context = {
        "allow_registration": settings.ALLOW_REGISTRATION,
        "email_enabled": settings.EMAIL_ENABLED,
    }
    # 只讓管理員看到設定上的問題
    user = getattr(request, "user", None)
    if user is not None and user.is_staff:
        context["config_warnings"] = [message for _, message in configuration_warnings()]
    return context
