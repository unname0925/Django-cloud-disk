"""一次處理多個勾選的檔案與資料夾。"""
from django.db import transaction

from ..models import Folder, StoredFile
from . import trash


class InvalidMove(Exception):
    pass


def selected_items(user, file_ids, folder_ids):
    """取得勾選的項目，並排除已經包含在勾選資料夾裡的檔案與子資料夾。

    同時勾選資料夾與它裡面的項目時，只處理資料夾本身，裡面的項目會跟著一起處理；
    否則移到回收筒時會被分成不同批次，還原資料夾時裡面的項目會被留下。
    """
    folders = list(Folder.objects.active().filter(owner=user, pk__in=folder_ids))
    covered = {}
    for folder in folders:
        for pk in folder.descendant_ids():
            if pk != folder.pk:
                covered[pk] = folder
    folders = [f for f in folders if f.pk not in covered]
    covered_ids = set(covered) | {f.pk for f in folders}
    files = [
        f for f in StoredFile.objects.active().filter(owner=user, pk__in=file_ids)
        if f.folder_id not in covered_ids
    ]
    return folders, files


def move_folder(folder, target):
    if target is not None and target.pk in folder.descendant_ids():
        raise InvalidMove(f"無法把「{folder.name}」移到它自己或子資料夾裡")
    if folder.parent_id == (target.pk if target else None):
        return
    folder.name = trash.unique_folder_name(folder.owner, target, folder.name, folder.pk)
    folder.parent = target
    folder.save(update_fields=["parent", "name"])


@transaction.atomic
def move_items(folders, files, target):
    """回傳無法移動的項目說明列表。"""
    errors = []
    for folder in folders:
        try:
            move_folder(folder, target)
        except InvalidMove as error:
            errors.append(str(error))
    for stored in files:
        stored.folder = target
        stored.save(update_fields=["folder"])
    return errors


@transaction.atomic
def trash_items(folders, files):
    for stored in files:
        trash.trash_file(stored)
    for folder in folders:
        trash.trash_folder(folder)


def folder_choices(user):
    """所有未刪除資料夾的 (id, 完整路徑)，一次查詢後在記憶體中組出路徑。"""
    queryset = Folder.objects.active().filter(owner=user).only("pk", "name", "parent_id")
    folders = {f.pk: f for f in queryset}
    paths = {}

    def path_of(folder):
        if folder.pk not in paths:
            parent = folders.get(folder.parent_id)
            paths[folder.pk] = f"{path_of(parent)} / {folder.name}" if parent else folder.name
        return paths[folder.pk]

    return sorted(((pk, path_of(f)) for pk, f in folders.items()), key=lambda item: item[1])
