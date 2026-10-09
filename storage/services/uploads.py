"""上傳相關邏輯：容量檢查、分段上傳（可續傳）、重複內容與版本處理。"""
import os
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.template.defaultfilters import filesizeformat

from ..models import StoredFile, UploadSession, UserProfile, upload_to_user
from . import versions
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


@dataclass
class UploadResult:
    stored: StoredFile
    # created：新檔案；updated：同名檔案的新版本；unchanged：內容和目前版本相同
    outcome: str
    # 內容和使用者其他檔案相同，共用了實體檔案
    shared_storage: bool = False

    def message(self):
        name = self.stored.original_name
        if self.outcome == "updated":
            return f"已更新「{name}」，舊版本已保留，可在「版本」中還原"
        if self.outcome == "unchanged":
            return f"「{name}」的內容和目前版本相同，沒有建立新版本"
        if self.shared_storage:
            return f"{name} 與既有檔案內容相同，已共用儲存空間，不會重複佔用容量"
        return None


def _physical_path(owner, filename):
    storage = StoredFile._meta.get_field("file").storage
    name = storage.get_available_name(upload_to_user(StoredFile(owner=owner), filename))
    return storage, name


def commit_upload(owner, folder, filename, size, digest, write_physical):
    """建立或更新檔案紀錄。

    write_physical(storage, name) 負責把內容寫到指定位置並回傳實際使用的名稱，
    只有在沒有可共用的實體檔案時才會被呼叫。同一個資料夾已有同名檔案時，
    舊內容會保存成版本。
    """
    duplicate = find_duplicate(owner, digest, size)
    current = (
        StoredFile.objects.active()
        .filter(owner=owner, folder=folder, original_name=filename)
        .order_by("-uploaded_time")
        .first()
    )
    if current is not None and current.sha256 == digest and current.file_size == size:
        return UploadResult(current, "unchanged")

    if duplicate is not None:
        name = duplicate.file.name
    else:
        storage, name = _physical_path(owner, filename)
        name = write_physical(storage, name)

    if current is not None:
        versions.add_version(current, name, size, digest)
        return UploadResult(current, "updated", shared_storage=duplicate is not None)

    stored = StoredFile.objects.create(
        owner=owner, folder=folder, file=name, original_name=filename,
        file_size=size, sha256=digest,
    )
    return UploadResult(stored, "created", shared_storage=duplicate is not None)


def store_uploaded_file(user, folder, uploaded):
    """儲存一般表單上傳的檔案，回傳 UploadResult。"""
    digest = sha256_of_chunks(uploaded.chunks())
    uploaded.seek(0)

    def write(storage, name):
        return storage.save(name, uploaded)

    return commit_upload(
        user, folder, clean_filename(uploaded.name), uploaded.size, digest, write
    )


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
    """組合完成的分段上傳，回傳 UploadResult。"""
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

    def move_part(storage, name):
        destination = Path(storage.path(name))
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, destination)
        return name

    result = commit_upload(
        session.owner, folder, session.filename, session.total_size, digest, move_part
    )
    # 共用既有實體檔案或內容沒變時，暫存檔沒有被搬走
    part.unlink(missing_ok=True)
    session.delete()
    return result


def cancel(session):
    session.part_path.unlink(missing_ok=True)
    session.delete()
