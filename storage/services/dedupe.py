"""重複檔案：用 SHA-256 判斷內容相同的檔案，讓同一位使用者的相同內容只存一份。"""
import hashlib

from django.db import transaction
from django.db.models import Count

from ..models import StoredFile
from .thumbnails import delete_thumbnail

HASH_BLOCK = 1024 * 1024


def sha256_of_chunks(chunks):
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


def sha256_of_path(path):
    with open(path, "rb") as fh:
        return sha256_of_chunks(iter(lambda: fh.read(HASH_BLOCK), b""))


def find_duplicate(owner, sha256, size, exclude_pk=None):
    """找出同一位使用者內容相同、而且實體檔案還在的檔案（包含回收筒裡的）。"""
    if not sha256:
        return None
    candidates = StoredFile.objects.filter(owner=owner, sha256=sha256, file_size=size)
    if exclude_pk is not None:
        candidates = candidates.exclude(pk=exclude_pk)
    for candidate in candidates.order_by("pk"):
        if candidate.file.storage.exists(candidate.file.name):
            return candidate
    return None


def _point_to(stored, existing):
    """讓 stored 改用 existing 的實體檔案，原本的實體檔案在沒有其他紀錄使用時刪除。"""
    old_name = stored.file.name
    stored.file.name = existing.file.name
    stored.save(update_fields=["file", "sha256"])
    storage = stored.file.storage

    def remove_if_unused():
        if old_name and not StoredFile.objects.filter(file=old_name).exists():
            storage.delete(old_name)
            delete_thumbnail(storage, old_name)

    transaction.on_commit(remove_if_unused)


def backfill(owner=None, limit=None):
    """補算舊檔案的 SHA-256，並合併內容相同的檔案。回傳 (處理數, 合併數, 剩餘數)。"""
    pending = StoredFile.objects.filter(sha256="").order_by("pk")
    if owner is not None:
        pending = pending.filter(owner=owner)
    batch = list(pending[:limit] if limit else pending)

    processed = merged = 0
    for stored in batch:
        try:
            stored.sha256 = sha256_of_path(stored.file.path)
        except FileNotFoundError:
            continue
        processed += 1
        existing = find_duplicate(stored.owner, stored.sha256, stored.file_size, stored.pk)
        if existing is not None and existing.file.name != stored.file.name:
            _point_to(stored, existing)
            merged += 1
        else:
            stored.save(update_fields=["sha256"])

    remaining = pending.count() if limit else 0
    return processed, merged, remaining


def duplicate_groups(owner):
    """使用者未刪除的檔案中，內容相同的群組。"""
    hashes = (
        StoredFile.objects.active()
        .filter(owner=owner)
        .exclude(sha256="")
        .values("sha256")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
        .values_list("sha256", flat=True)
    )
    groups = []
    for sha256 in hashes:
        files = list(
            StoredFile.objects.active()
            .filter(owner=owner, sha256=sha256)
            .select_related("folder")
            .order_by("uploaded_time")
        )
        groups.append({"sha256": sha256, "size": files[0].file_size, "files": files})
    groups.sort(key=lambda g: g["size"] * (len(g["files"]) - 1), reverse=True)
    return groups
