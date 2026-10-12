from django.core.checks import Tags, Warning, register

from .health import configuration_warnings


@register(Tags.security, deploy=True)
def deployment_settings(app_configs, **kwargs):
    """執行 manage.py check --deploy 時檢查正式環境的常見設定問題。"""
    return [Warning(message, id=code) for code, message in configuration_warnings()]
