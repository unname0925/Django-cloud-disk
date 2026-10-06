import mimetypes
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum
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
        return StoredFile.objects.filter(owner=self.user).aggregate(
            total=Sum("file_size")
        )["total"] or 0

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


class ShareLink(models.Model):
    file = models.ForeignKey(StoredFile, on_delete=models.CASCADE, related_name="share_links")
    token = models.CharField(max_length=64, unique=True, default=generate_share_token)
    created_time = models.DateTimeField(auto_now_add=True)
    expires_time = models.DateTimeField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_time"]

    def __str__(self):
        return f"{self.file.original_name} ({self.token[:8]}…)"

    @property
    def is_expired(self):
        return self.expires_time is not None and self.expires_time <= timezone.now()


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
