import mimetypes
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.contrib.auth.hashers import check_password
from django.db.models import Q
from django.utils import timezone
from django.utils.text import get_valid_filename

# 可以在瀏覽器中直接預覽的檔案類型；HTML、SVG 等可能夾帶腳本的類型一律只能下載
PREVIEWABLE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/plain",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "video/mp4",
    "video/webm",
}


# 可以產生縮圖的圖片類型
THUMBNAIL_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def upload_to_user(instance, filename):
    """檔案存放於 users/<使用者資料夾 UUID>/<隨機前綴>_<安全檔名>。"""
    safe_name = get_valid_filename(Path(filename).name) or "file"
    profile = UserProfile.for_user(instance.owner)
    return f"users/{profile.folder_uuid}/{uuid.uuid4().hex}_{safe_name}"


def upload_temp_dir():
    """分段上傳的暫存目錄。

    放在 MEDIA_ROOT 底下，確保和最終位置在同一個檔案系統，完成時可以直接搬移而不必複製。
    """
    return Path(settings.MEDIA_ROOT) / "tmp_uploads"


def generate_share_token():
    return secrets.token_urlsafe(24)


class TrashableQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_time__isnull=True)

    def trashed(self):
        return self.filter(deleted_time__isnull=False)


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    folder_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    quota_bytes = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="留空則使用預設容量（STORAGE_DEFAULT_QUOTA_MB）"
    )
    created_time = models.DateTimeField(auto_now_add=True)

    # 兩步驟驗證（TOTP）
    totp_secret = models.CharField(max_length=64, blank=True)
    totp_enabled = models.BooleanField(default=False)
    # 最後一次成功使用的時間區段，用來防止同一組驗證碼被重複使用
    totp_last_step = models.BigIntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} profile"

    @classmethod
    def for_user(cls, user):
        profile, _ = cls.objects.get_or_create(user=user)
        return profile

    @property
    def quota(self):
        if self.quota_bytes is None:
            return settings.STORAGE_DEFAULT_QUOTA
        return self.quota_bytes

    @property
    def used_bytes(self):
        # 內容相同的檔案（包含舊版本）共用同一個實體檔案，容量只算一次
        sizes = dict(StoredFile.objects.filter(owner=self.user).values_list("file", "file_size"))
        sizes.update(
            FileVersion.objects.filter(stored_file__owner=self.user)
            .values_list("file", "file_size")
        )
        return sum(sizes.values())

    @property
    def remaining_bytes(self):
        return max(self.quota - self.used_bytes, 0)


class Folder(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="folders"
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    name = models.CharField(max_length=255)
    created_time = models.DateTimeField(auto_now_add=True)
    # 丟進資源回收筒的時間；資料夾內的子資料夾與檔案會標記相同時間
    deleted_time = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = TrashableQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        # 只限制「未刪除」的資料夾不可同名，回收筒裡的同名資料夾不受影響
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "parent", "name"],
                condition=Q(deleted_time__isnull=True),
                name="unique_active_folder_name_in_parent",
            ),
            models.UniqueConstraint(
                fields=["owner", "name"],
                condition=Q(parent__isnull=True, deleted_time__isnull=True),
                name="unique_active_folder_name_in_root",
            ),
        ]

    def __str__(self):
        return self.name

    def ancestors(self):
        """從根目錄到自己（含自己）的資料夾清單，用於麵包屑導覽。"""
        chain = []
        folder = self
        while folder is not None:
            chain.append(folder)
            folder = folder.parent
        return list(reversed(chain))

    def descendant_ids(self):
        """自己與所有子孫資料夾的 id。"""
        ids, frontier = [self.pk], [self.pk]
        while frontier:
            frontier = list(
                Folder.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
            )
            ids.extend(frontier)
        return ids


class StoredFile(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stored_files"
    )
    folder = models.ForeignKey(
        Folder, null=True, blank=True, on_delete=models.CASCADE, related_name="files"
    )
    file = models.FileField(upload_to=upload_to_user)
    original_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    uploaded_time = models.DateTimeField(auto_now_add=True)
    deleted_time = models.DateTimeField(null=True, blank=True, db_index=True)
    # 內容的 SHA-256，用來偵測重複檔案；舊檔案由 cleanup_storage 補算
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)

    objects = TrashableQuerySet.as_manager()

    class Meta:
        ordering = ["-uploaded_time"]

    def __str__(self):
        return f"{self.original_name} ({self.owner.username})"

    @property
    def content_type(self):
        # 依檔名判斷，不採用瀏覽器上傳時宣稱的類型
        guessed, _ = mimetypes.guess_type(self.original_name)
        return guessed or "application/octet-stream"

    @property
    def is_previewable(self):
        return self.content_type in PREVIEWABLE_TYPES

    @property
    def is_image(self):
        return self.content_type in THUMBNAIL_TYPES

    @property
    def thumbnail_name(self):
        return f"thumbs/{self.file.name}.jpg"


class FileVersion(models.Model):
    """檔案的舊版本。上傳同名檔案到同一個資料夾時，原本的內容會保存成一個版本。"""

    stored_file = models.ForeignKey(StoredFile, on_delete=models.CASCADE, related_name="versions")
    file = models.FileField()
    file_size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    # 這個版本原本上傳的時間
    created_time = models.DateTimeField()
    # 被新版本取代的時間
    replaced_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_time"]

    def __str__(self):
        return f"{self.stored_file.original_name} @ {self.created_time:%Y-%m-%d %H:%M}"


def physical_file_in_use(name):
    """內容相同的檔案與舊版本可能共用實體檔案，只要還有任何紀錄使用就不能刪除。"""
    return (
        StoredFile.objects.filter(file=name).exists()
        or FileVersion.objects.filter(file=name).exists()
    )


class ShareLink(models.Model):
    """分享單一檔案或整個資料夾的連結（file 與 folder 恰好其中一個有值）。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="share_links"
    )
    file = models.ForeignKey(
        StoredFile, null=True, blank=True, on_delete=models.CASCADE, related_name="share_links"
    )
    folder = models.ForeignKey(
        Folder, null=True, blank=True, on_delete=models.CASCADE, related_name="share_links"
    )
    token = models.CharField(max_length=64, unique=True, default=generate_share_token)
    created_time = models.DateTimeField(auto_now_add=True)
    expires_time = models.DateTimeField(null=True, blank=True)
    password_hash = models.CharField(max_length=128, blank=True)
    max_downloads = models.PositiveIntegerField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_time"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(file__isnull=False, folder__isnull=True)
                    | Q(file__isnull=True, folder__isnull=False)
                ),
                name="share_link_has_one_target",
            ),
        ]

    def __str__(self):
        return f"{self.target_name} ({self.token[:8]}…)"

    @property
    def target(self):
        return self.file if self.file_id else self.folder

    @property
    def target_name(self):
        return self.file.original_name if self.file_id else self.folder.name

    @property
    def is_expired(self):
        return self.expires_time is not None and self.expires_time <= timezone.now()

    @property
    def is_exhausted(self):
        return self.max_downloads is not None and self.download_count >= self.max_downloads

    @property
    def target_in_trash(self):
        return self.target.deleted_time is not None

    @property
    def is_active(self):
        return not (self.is_expired or self.is_exhausted or self.target_in_trash)

    @property
    def has_password(self):
        return bool(self.password_hash)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)


class RecoveryCode(models.Model):
    """兩步驟驗證的備用碼，只儲存雜湊值，每組只能使用一次。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_codes"
    )
    code_hash = models.CharField(max_length=64)
    used_time = models.DateTimeField(null=True, blank=True)


class UploadSession(models.Model):
    """分段上傳中的檔案；所有分段收齊後才會建立 StoredFile。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="upload_sessions"
    )
    folder = models.ForeignKey(
        Folder, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    filename = models.CharField(max_length=255)
    total_size = models.PositiveBigIntegerField()
    received_bytes = models.PositiveBigIntegerField(default=0)
    created_time = models.DateTimeField(auto_now_add=True)
    updated_time = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.filename} ({self.received_bytes}/{self.total_size})"

    @property
    def part_path(self):
        return upload_temp_dir() / f"{self.pk}.part"


class ActivityLog(models.Model):
    """使用者的登入與操作紀錄。"""

    class Action(models.TextChoices):
        LOGIN = "login", "登入"
        LOGIN_FAILED = "login_failed", "登入失敗"
        TWO_FACTOR_FAILED = "two_factor_failed", "驗證碼錯誤"
        LOGOUT = "logout", "登出"
        PASSWORD_CHANGE = "password_change", "變更密碼"
        TWO_FACTOR_ENABLE = "two_factor_enable", "啟用兩步驟驗證"
        TWO_FACTOR_DISABLE = "two_factor_disable", "停用兩步驟驗證"
        RECOVERY_CODES = "recovery_codes", "重新產生備用碼"
        UPLOAD = "upload", "上傳"
        UPDATE = "update", "上傳新版本"
        TRASH = "trash", "移到回收筒"
        RESTORE = "restore", "從回收筒還原"
        PURGE = "purge", "永久刪除"
        MOVE = "move", "移動"
        VERSION_RESTORE = "version_restore", "還原舊版本"
        SHARE_CREATE = "share_create", "建立分享連結"
        SHARE_REVOKE = "share_revoke", "撤銷分享連結"
        SHARE_DOWNLOAD = "share_download", "分享連結被下載"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
        related_name="activity_logs",
    )
    # 登入失敗時使用者可能不存在，保留輸入的帳號
    username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)
    target = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_time = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_time", "-pk"]

    def __str__(self):
        return f"{self.username} {self.get_action_display()} {self.target}"

    @property
    def device(self):
        """從 User-Agent 粗略判斷瀏覽器與作業系統。"""
        ua = self.user_agent
        if not ua:
            return ""
        browser = next((name for key, name in (
            ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
            ("Chrome/", "Chrome"), ("Safari/", "Safari"),
        ) if key in ua), "其他瀏覽器")
        system = next((name for key, name in (
            ("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
            ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Linux", "Linux"),
        ) if key in ua), "")
        return f"{browser}（{system}）" if system else browser
