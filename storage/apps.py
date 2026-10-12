from importlib import import_module

from django.apps import AppConfig


class StorageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "storage"

    def ready(self):
        # 註冊 signal receiver 與系統檢查
        import_module(f"{self.name}.signals")
        import_module(f"{self.name}.checks")
