"""部署健檢：執行期的健康檢查，以及設定上的常見問題。"""
import shutil
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.db import connection

from .services.backup import last_offsite_success, latest_backup

DEFAULT_URL_PREFIX = "x8FqP2vM4wA1"

OK, WARNING, ERROR = "ok", "warning", "error"


# --- 設定檢查 ---------------------------------------------------------------


def configuration_warnings():
    """正式環境常見的設定問題，回傳 (代碼, 說明) 列表。開發模式下不檢查。"""
    if settings.DEBUG:
        return []
    warnings = []
    if settings.SECRET_URL_PREFIX == DEFAULT_URL_PREFIX:
        warnings.append((
            "storage.W001",
            "SECRET_URL_PREFIX 仍是程式碼中的預設值，這個值已公開在 GitHub 上，請改成自己的隨機字串",
        ))
    if settings.ALLOW_REGISTRATION:
        warnings.append((
            "storage.W002",
            "目前開放任何人註冊；只給自己或家人使用時，建議設定 ALLOW_REGISTRATION=False",
        ))
    if not settings.USE_HTTPS:
        warnings.append((
            "storage.W003",
            "沒有啟用 HTTPS（USE_HTTPS=False），帳號密碼與檔案會以明文傳送",
        ))
    if settings.TRUST_PROXY_HEADERS and not settings.USE_HTTPS:
        warnings.append((
            "storage.W004",
            "TRUST_PROXY_HEADERS=True 但 USE_HTTPS=False，請確認反向代理已設定 HTTPS",
        ))
    return warnings


# --- 執行期健康檢查 ---------------------------------------------------------


def _check_database():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return OK, "資料庫連線正常"
    except Exception as error:  # noqa: BLE001 - 健康檢查要回報任何錯誤
        return ERROR, f"資料庫無法連線：{error.__class__.__name__}"


def _check_storage():
    media_root = Path(settings.MEDIA_ROOT)
    try:
        media_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=media_root, prefix=".healthcheck-"):
            pass
        return OK, "檔案目錄可以寫入"
    except OSError as error:
        return ERROR, f"檔案目錄無法寫入：{error.strerror or error.__class__.__name__}"


def _check_disk():
    try:
        usage = shutil.disk_usage(settings.MEDIA_ROOT)
    except OSError:
        return ERROR, "無法取得硬碟空間"
    free_percent = usage.free * 100 / usage.total if usage.total else 0
    free_gb = usage.free / 1024**3
    message = f"硬碟剩餘 {free_gb:.1f} GB（{free_percent:.0f}%）"
    if free_percent < settings.HEALTH_MIN_FREE_PERCENT:
        return WARNING, message + "，空間快不夠了"
    return OK, message


def _check_backup():
    if not settings.AUTO_BACKUP:
        return None
    latest = latest_backup(settings.BACKUP_DIR)
    if latest is None:
        return WARNING, "已啟用自動備份，但還沒有任何備份"
    age_hours = (time.time() - latest.stat().st_mtime) / 3600
    message = f"最近一次備份在 {age_hours:.0f} 小時前"
    if age_hours > settings.HEALTH_MAX_BACKUP_AGE_HOURS:
        return WARNING, message + "，自動備份可能沒有正常執行"
    return OK, message


def _check_offsite_backup():
    if not (settings.BACKUP_COPY_DIR or settings.BACKUP_RCLONE_REMOTE):
        return None
    last = last_offsite_success(settings.BACKUP_DIR)
    if last is None:
        return WARNING, "已設定異地備份，但還沒有成功過"
    age_hours = (time.time() - last) / 3600
    message = f"最近一次異地備份在 {age_hours:.0f} 小時前"
    if age_hours > settings.HEALTH_MAX_BACKUP_AGE_HOURS:
        return WARNING, message + "，請檢查外接硬碟或雲端設定"
    return OK, message


CHECKS = {
    "database": _check_database,
    "storage": _check_storage,
    "disk": _check_disk,
    "backup": _check_backup,
    "offsite_backup": _check_offsite_backup,
}


def run_checks():
    """回傳 (整體狀態, {項目: {status, message}})。"""
    results = {}
    for name, check in CHECKS.items():
        outcome = check()
        if outcome is not None:
            status, message = outcome
            results[name] = {"status": status, "message": message}
    statuses = {item["status"] for item in results.values()}
    overall = ERROR if ERROR in statuses else WARNING if WARNING in statuses else OK
    return overall, results

