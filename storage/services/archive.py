"""把資料夾打包成 zip。"""
import shutil
import tempfile
import zipfile

from django.utils import timezone

from ..models import Folder, StoredFile

# 這些格式本身已經壓縮過，再壓縮只是浪費 CPU
STORED_PREFIXES = ("image/", "video/", "audio/")
STORED_TYPES = {"application/zip", "application/gzip", "application/x-7z-compressed",
                "application/x-rar-compressed", "application/pdf"}


def _clean(part):
    return part.replace("/", "_").replace("\\", "_")


def _unique(name, used):
    if name not in used:
        used.add(name)
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot or "/" in ext:
        stem, ext = name, ""
    counter = 2
    while True:
        candidate = f"{stem} ({counter}){'.' + ext if ext else ''}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def _write_zip(folders, files, root_paths):
    """把資料夾與檔案寫入暫存的 zip。root_paths 指定最上層資料夾在壓縮檔中的路徑。"""
    folder_map = {f.pk: f for f in folders}
    paths = {}
    used = set()

    def path_of(f):
        # 回傳資料夾在壓縮檔中的路徑（結尾含 /）
        if f.pk not in paths:
            if f.pk in root_paths:
                paths[f.pk] = root_paths[f.pk]
            else:
                parent = folder_map.get(f.parent_id)
                prefix = path_of(parent) if parent else ""
                paths[f.pk] = f"{prefix}{_clean(f.name)}/"
        return paths[f.pk]

    archive = tempfile.TemporaryFile()
    with zipfile.ZipFile(archive, "w") as zf:
        for f in folder_map.values():
            path = path_of(f)
            if path and path not in used:
                zf.writestr(zipfile.ZipInfo(path), b"")
                used.add(path)

        for stored in sorted(files, key=lambda item: item.pk):
            parent = folder_map.get(stored.folder_id)
            prefix = path_of(parent) if parent else ""
            info = zipfile.ZipInfo(_unique(prefix + _clean(stored.original_name), used))
            info.date_time = timezone.localtime(stored.uploaded_time).timetuple()[:6]
            info.file_size = stored.file_size
            content_type = stored.content_type
            info.compress_type = (
                zipfile.ZIP_STORED
                if content_type.startswith(STORED_PREFIXES) or content_type in STORED_TYPES
                else zipfile.ZIP_DEFLATED
            )
            try:
                with stored.file.open("rb") as src, zf.open(info, "w") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
            except FileNotFoundError:
                continue

    archive.seek(0)
    return archive


def build_zip(user, folder=None):
    """打包單一資料夾（內容放在壓縮檔最上層）或使用者的全部檔案。

    回傳 (暫存檔, 下載檔名)。暫存檔關閉後會自動刪除。
    """
    folders = Folder.objects.active().filter(owner=user)
    files = StoredFile.objects.active().filter(owner=user)
    root_paths = {}
    if folder is not None:
        folder_ids = folder.descendant_ids()
        folders = folders.filter(pk__in=folder_ids)
        files = files.filter(folder_id__in=folder_ids)
        root_paths = {folder.pk: ""}

    archive = _write_zip(list(folders), list(files), root_paths)
    name = folder.name if folder is not None else "我的檔案"
    return archive, f"{name}.zip"


def build_selection_zip(user, selected_folders, selected_files):
    """打包勾選的資料夾（各自保留資料夾名稱）與檔案。"""
    folder_ids = {pk for f in selected_folders for pk in f.descendant_ids()}
    folders = list(Folder.objects.active().filter(owner=user, pk__in=folder_ids))
    files = {f.pk: f for f in StoredFile.objects.active().filter(owner=user,
                                                                 folder_id__in=folder_ids)}
    for stored in selected_files:
        files.setdefault(stored.pk, stored)

    root_names = set()
    root_paths = {}
    for f in selected_folders:
        # 不同位置的資料夾可能同名，加上編號避免衝突
        root_paths[f.pk] = _unique(_clean(f.name), root_names) + "/"
    # 勾選的檔案若不在勾選的資料夾內，_write_zip 會放在壓縮檔最上層
    archive = _write_zip(folders, list(files.values()), root_paths)
    return archive, "已選取的檔案.zip"
