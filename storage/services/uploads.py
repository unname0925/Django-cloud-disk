"""上傳相關邏輯：容量檢查與分段上傳（可續傳）。"""
import os
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.template.defaultfilters import filesizeformat

from ..models import StoredFile, UploadSession, UserProfile, upload_to_user
from .dedupe import find_duplicate, sha256_of_chunks, sha256_of_path

INVALID_FILENAME_CHARS = '/\\:*?"<>|'


class UploadError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def clean_filename(name):
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    for char in INVALID_FILENAME_CHARS:
        name = name.replace(char, "_")
    name = name.strip()[:255]
    return name if name not in ("", ".", "..") else "file"


def check_upload_allowed(user, sizes):
    """檢查單檔上限與剩餘容量，不允許時丟出 UploadError。"""
    max_size = settings.STORAGE_MAX_UPLOAD_SIZE
    for name, size in sizes:
        if size > max_size:
            raise UploadError(f"「{name}」超過單檔上限 {filesizeformat(max_size)}", 413)

    remaining = UserProfile.for_user(user).remaining_bytes
    total = sum(size for _, size in sizes)
    if total > remaining:
        raise UploadError(
            f"容量不足：本次上傳 {filesizeformat(total)}，剩餘 {filesizeformat(remaining)}", 413
        )


def store_uploaded_file(user, folder, uploaded):
    """儲存一般表單上傳的檔案；內容和既有檔案相同時共用實體檔案。

    回傳 (StoredFile, 重複的既有檔案或 None)。
    """
    digest = sha256_of_chunks(uploaded.chunks())
    uploaded.seek(0)
    existing = find_duplicate(user, digest, uploaded.size)
    stored = StoredFile.objects.create(
        owner=user,
        folder=folder,
        file=existing.file.name if existing else uploaded,
        original_name=clean_filename(uploaded.name),
        file_size=uploaded.size,
        sha256=digest,
    )
    return stored, existing


def start_session(user, filename, total_size, folder):
    filename = clean_filename(filename)
    check_upload_allowed(user, [(filename, total_size)])
    session = UploadSession.objects.create(
        owner=user, folder=folder, filename=filename, total_size=total_size
    )
    if total_size == 0:
        return session, finalize(session)
    return session, None


def append_chunk(session, offset, chunk):
    """寫入一個分段；所有分段收齊後回傳建立好的 StoredFile。"""
    with transaction.atomic():
        session = UploadSession.objects.select_for_update().get(pk=session.pk)
        if offset != session.received_bytes:
            raise UploadError("分段位置不符", 409)
        if chunk.size == 0 or chunk.size > settings.STORAGE_CHUNK_SIZE:
            raise UploadError("分段大小不正確")
        if offset + chunk.size > session.total_size:
            raise UploadError("資料超過檔案大小")

        path = session.part_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "r+b" if path.exists() else "wb") as fh:
            # 若上次寫入後伺服器在更新資料庫前中斷，這裡會覆蓋掉多出來的資料
            fh.seek(offset)
            for piece in chunk.chunks():
                fh.write(piece)
            fh.truncate()

        session.received_bytes = offset + chunk.size
        session.save(update_fields=["received_bytes", "updated_time"])

    if session.received_bytes == session.total_size:
        return session, finalize(session)
    return session, None


def finalize(session):
    """組合完成的分段上傳，回傳 StoredFile（重複的既有檔案記在 stored.duplicate_of）。"""
    try:
        # 上傳期間可能已經用掉其他容量，完成前再檢查一次
        check_upload_allowed(session.owner, [(session.filename, session.total_size)])
    except UploadError:
        cancel(session)
        raise

    folder = session.folder
    if folder is not None and folder.deleted_time is not None:
        folder = None

    part = session.part_path
    if not part.exists():
        part.touch()  # 空檔案不會有任何分段
    digest = sha256_of_path(part)

    stored = StoredFile(
        owner=session.owner,
        folder=folder,
        original_name=session.filename,
        file_size=session.total_size,
        sha256=digest,
    )
    existing = find_duplicate(session.owner, digest, session.total_size)
    if existing is not None:
        part.unlink()
        name = existing.file.name
    else:
        storage = stored.file.storage
        name = storage.get_available_name(upload_to_user(stored, session.filename))
        destination = Path(storage.path(name))
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, destination)

    stored.file.name = name
    stored.save()
    session.delete()
    stored.duplicate_of = existing
    return stored


def cancel(session):
    session.part_path.unlink(missing_ok=True)
    session.delete()
