"""資源回收筒：刪除時先標記 deleted_time，保留期限過後才永久刪除。

丟棄資料夾時，資料夾內所有尚未刪除的子資料夾與檔案會標記相同的 deleted_time，
還原時只還原同一批丟棄的項目，先前個別丟棄的項目仍留在回收筒。
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import Folder, StoredFile


def trash_file(stored_file):
    stored_file.deleted_time = timezone.now()
    stored_file.save(update_fields=["deleted_time"])


@transaction.atomic
def trash_folder(folder):
    now = timezone.now()
    ids = folder.descendant_ids()
    Folder.objects.active().filter(pk__in=ids).update(deleted_time=now)
    StoredFile.objects.active().filter(folder_id__in=ids).update(deleted_time=now)


def unique_folder_name(owner, parent, name, exclude_pk=None):
    """回傳同一位置下不重複的資料夾名稱，例如「docs (2)」。"""
    siblings = Folder.objects.active().filter(owner=owner, parent=parent)
    if exclude_pk is not None:
        siblings = siblings.exclude(pk=exclude_pk)
    candidate, counter = name, 2
    while siblings.filter(name=candidate).exists():
        candidate = f"{name} ({counter})"
        counter += 1
    return candidate


def restore_file(stored_file):
    # 原本的資料夾還在回收筒裡時，改還原到根目錄
    if stored_file.folder_id and stored_file.folder.deleted_time is not None:
        stored_file.folder = None
    stored_file.deleted_time = None
    stored_file.save(update_fields=["folder", "deleted_time"])


@transaction.atomic
def restore_folder(folder):
    batch_time = folder.deleted_time
    ids = folder.descendant_ids()

    if folder.parent_id and folder.parent.deleted_time is not None:
        folder.parent = None
    folder.name = unique_folder_name(folder.owner, folder.parent, folder.name, folder.pk)
    folder.deleted_time = None
    folder.save(update_fields=["parent", "name", "deleted_time"])

    Folder.objects.filter(pk__in=ids, deleted_time=batch_time).update(deleted_time=None)
    StoredFile.objects.filter(folder_id__in=ids, deleted_time=batch_time).update(deleted_time=None)


def trash_roots(user):
    """回收筒中「最上層」的項目：所在資料夾本身沒有被丟棄的資料夾與檔案。"""
    folders = (
        Folder.objects.trashed()
        .filter(owner=user)
        .filter(Q(parent__isnull=True) | Q(parent__deleted_time__isnull=True))
        .order_by("-deleted_time")
    )
    files = (
        StoredFile.objects.trashed()
        .filter(owner=user)
        .filter(Q(folder__isnull=True) | Q(folder__deleted_time__isnull=True))
        .order_by("-deleted_time")
    )
    return folders, files


def expires_at(deleted_time):
    return deleted_time + timedelta(days=settings.STORAGE_TRASH_RETENTION_DAYS)


def purge_expired(user=None):
    """永久刪除超過保留期限的項目，回傳刪除的檔案數。"""
    cutoff = timezone.now() - timedelta(days=settings.STORAGE_TRASH_RETENTION_DAYS)
    folders = Folder.objects.filter(deleted_time__lt=cutoff)
    files = StoredFile.objects.filter(deleted_time__lt=cutoff)
    if user is not None:
        folders, files = folders.filter(owner=user), files.filter(owner=user)
    return _delete(folders, files)


def empty_trash(user):
    return _delete(
        Folder.objects.trashed().filter(owner=user),
        StoredFile.objects.trashed().filter(owner=user),
    )


def _delete(folders, files):
    # 實體檔案由 post_delete signal 清除；資料夾刪除時其中的檔案會連帶刪除
    with transaction.atomic():
        folder_ids = [pk for f in folders for pk in f.descendant_ids()]
        file_count = StoredFile.objects.filter(
            Q(pk__in=files.values("pk")) | Q(folder_id__in=folder_ids)
        ).count()
        folders.delete()
        files.delete()
    return file_count
