import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value else default


def env_list(name, default):
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


MB = 1024 * 1024

# --- 基本設定 ---------------------------------------------------------------

DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("正式環境必須設定 DJANGO_SECRET_KEY 環境變數")
    SECRET_KEY = "django-insecure-dev-only-key"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

# 所有頁面都掛在這個前綴底下，請透過環境變數設定自己的值
SECRET_URL_PREFIX = os.environ.get("SECRET_URL_PREFIX", "x8FqP2vM4wA1").strip("/")

# --- 雲端硬碟功能設定 -------------------------------------------------------

# 是否開放註冊；只給自己和家人用時建議關閉，改由管理員在後台建立帳號
ALLOW_REGISTRATION = env_bool("ALLOW_REGISTRATION", True)

# 同一個 IP 每天最多可以註冊幾個帳號
REGISTRATIONS_PER_IP_PER_DAY = env_int("REGISTRATIONS_PER_IP_PER_DAY", 3)

# 每位使用者的預設容量（可在後台針對個別使用者調整）
STORAGE_DEFAULT_QUOTA = env_int("STORAGE_DEFAULT_QUOTA_MB", 1024) * MB

# 單一檔案上傳大小上限
STORAGE_MAX_UPLOAD_SIZE = env_int("STORAGE_MAX_UPLOAD_SIZE_MB", 100) * MB

# 資源回收筒保留天數，超過後自動永久刪除
STORAGE_TRASH_RETENTION_DAYS = env_int("STORAGE_TRASH_RETENTION_DAYS", 30)

# 拖曳上傳時每個分段的大小；上傳中斷可從最後完成的分段續傳
STORAGE_CHUNK_SIZE = env_int("STORAGE_CHUNK_SIZE_MB", 5) * MB

# 未完成的分段上傳保留多久（小時），超過後由 cleanup_storage 指令清除
STORAGE_UPLOAD_SESSION_HOURS = env_int("STORAGE_UPLOAD_SESSION_HOURS", 24)

# 每個檔案最多保留幾個舊版本（上傳同名檔案到同一個資料夾時產生）
STORAGE_MAX_VERSIONS = env_int("STORAGE_MAX_VERSIONS", 10)

# 縮圖最長邊（像素）
STORAGE_THUMBNAIL_SIZE = 320

# 超過這個像素數的圖片不產生縮圖（約 1 億像素，例如 12000×8000）
STORAGE_THUMBNAIL_MAX_PIXELS = env_int("STORAGE_THUMBNAIL_MAX_PIXELS", 100_000_000)

# Docker 部署時每天自動備份；啟用時健康檢查也會確認最近的備份夠新
AUTO_BACKUP = env_bool("AUTO_BACKUP", False)

# 健康檢查：硬碟剩餘空間低於這個百分比、或最近的備份超過這個時數時發出警告
HEALTH_MIN_FREE_PERCENT = env_int("HEALTH_MIN_FREE_PERCENT", 5)
HEALTH_MAX_BACKUP_AGE_HOURS = env_int("HEALTH_MAX_BACKUP_AGE_HOURS", 36)

# backup 指令的預設存放位置與保留份數
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", BASE_DIR / "backups"))
BACKUP_KEEP = env_int("BACKUP_KEEP", 7)

# 異地備份：備份和資料在同一顆硬碟上，硬碟壞掉時會一起不見
# BACKUP_COPY_DIR：另外複製到外接硬碟或 NAS 掛載的目錄
# BACKUP_RCLONE_REMOTE：用 rclone 上傳到雲端，例如 gdrive:cloud-disk-backups
BACKUP_COPY_DIR = os.environ.get("BACKUP_COPY_DIR", "")
BACKUP_RCLONE_REMOTE = os.environ.get("BACKUP_RCLONE_REMOTE", "")
BACKUP_OFFSITE_KEEP = env_int("BACKUP_OFFSITE_KEEP", 14)
RCLONE_BINARY = os.environ.get("RCLONE_BINARY", "rclone")

# 活動紀錄保留天數，超過後由 cleanup_storage 刪除
ACTIVITY_LOG_RETENTION_DAYS = env_int("ACTIVITY_LOG_RETENTION_DAYS", 180)

# 同一個 IP 連續登入失敗幾次後鎖定，以及鎖定秒數
LOGIN_MAX_ATTEMPTS = env_int("LOGIN_MAX_ATTEMPTS", 5)
LOGIN_LOCKOUT_SECONDS = env_int("LOGIN_LOCKOUT_SECONDS", 15 * 60)

# --- Django 設定 ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "storage.apps.StorageConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cloud.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.csp",
                "storage.context_processors.site_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "cloud.wsgi.application"
ASGI_APPLICATION = "cloud.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", BASE_DIR / "db.sqlite3"),
    }
}

# 多個 worker（例如 gunicorn）時請設定 CACHE_DIR，讓登入失敗次數在 worker 之間共用
if os.environ.get("CACHE_DIR"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": os.environ["CACHE_DIR"],
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hant"
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# 使用者檔案只能透過 view 檢查權限後下載，不會直接對外提供
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "private_storage"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "storage:login"
LOGIN_REDIRECT_URL = "storage:browse"
LOGOUT_REDIRECT_URL = "storage:login"

# --- Content-Security-Policy ------------------------------------------------

# 只允許載入本站的腳本與樣式，內嵌的 <style> 需要帶 nonce；
# 即使有地方忘了跳脫使用者輸入，注入的腳本也不會被執行
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF, CSP.NONCE],
    "img-src": [CSP.SELF, "data:"],
    "media-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}

# --- HTTPS ------------------------------------------------------------------

# 有架 HTTPS（例如 nginx + Let's Encrypt）時設為 True，Cookie 只會透過 HTTPS 傳送
USE_HTTPS = env_bool("USE_HTTPS", False)
SESSION_COOKIE_SECURE = USE_HTTPS
CSRF_COOKIE_SECURE = USE_HTTPS
SECURE_SSL_REDIRECT = USE_HTTPS
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

# 在 Caddy / nginx 等反向代理後方時設為 True：
# 透過 X-Forwarded-Proto 判斷 HTTPS，並用 X-Forwarded-For 取得使用者真實 IP。
# 沒有反向代理時請保持 False，否則使用者可以偽造 IP 繞過登入鎖定。
TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", False)
if TRUST_PROXY_HEADERS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # HSTS 由前面的 Caddy 加上，不需要 Django 再檢查
    SILENCED_SYSTEM_CHECKS = ["security.W004"]

# 健康檢查由容器內部以 HTTP 呼叫，不需要轉址到 HTTPS
SECURE_REDIRECT_EXEMPT = [rf"^{SECRET_URL_PREFIX}/healthz/$"]
