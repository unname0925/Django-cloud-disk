"""檔案版本歷史。"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import FileVersion


@transaction.atomic
def add_version(stored, name, size, sha256):
    """把 stored 目前的內容保存成舊版本，並換成新上傳的內容。"""
    FileVersion.objects.create(
        stored_file=stored,
        file=stored.file.name,
        file_size=stored.file_size,
        sha256=stored.sha256,
        created_time=stored.uploaded_time,
    )
    stored.file.name = name
    stored.file_size = size
    stored.sha256 = sha256
    stored.uploaded_time = timezone.now()
    stored.save(update_fields=["file", "file_size", "sha256", "uploaded_time"])
    prune(stored)


def prune(stored):
    """只保留最新的 STORAGE_MAX_VERSIONS 個舊版本，實體檔案由 signal 清除。"""
    extra = stored.versions.order_by("-created_time")[settings.STORAGE_MAX_VERSIONS:]
    FileVersion.objects.filter(pk__in=[v.pk for v in extra]).delete()


@transaction.atomic
def restore(version):
    """把舊版本換回目前的內容；目前的內容變成一個舊版本。"""
    stored = version.stored_file
    current = (stored.file.name, stored.file_size, stored.sha256, stored.uploaded_time)
    stored.file.name = version.file.name
    stored.file_size = version.file_size
    stored.sha256 = version.sha256
    stored.uploaded_time = version.created_time
    stored.save(update_fields=["file", "file_size", "sha256", "uploaded_time"])
    version.file.name, version.file_size, version.sha256, version.created_time = current
    version.replaced_time = timezone.now()
    version.save()
