"""備份與還原：資料庫快照加上使用者檔案，打包成一個 .tar.gz。"""
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connections
from django.utils import timezone

FORMAT_VERSION = 1
PREFIX = "cloud-disk-"
SUFFIX = ".tar.gz"
# 可以重新產生的內容不需要備份
SKIPPED_MEDIA_DIRS = {"tmp_uploads", "thumbs"}


class BackupError(Exception):
    pass


def database_path():
    database = settings.DATABASES["default"]
    if database["ENGINE"] != "django.db.backends.sqlite3":
        raise BackupError("目前只支援 SQLite 資料庫的備份與還原")
    return Path(database["NAME"])


def _media_files(media_root, exclude):
    for path in sorted(media_root.rglob("*")):
        relative = path.relative_to(media_root)
        if relative.parts[0] in SKIPPED_MEDIA_DIRS or path.is_dir():
            continue
        if exclude is not None and exclude in path.parents:
            continue
        yield path, relative


def create_backup(output_dir, include_files=True):
    """建立備份，回傳備份檔路徑。先寫到暫存檔，完成後才改名，避免留下不完整的備份。"""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    media_root = Path(settings.MEDIA_ROOT).resolve()
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    target = output_dir / f"{PREFIX}{stamp}{SUFFIX}"

    with tempfile.TemporaryDirectory() as workdir:
        # 用 SQLite 的 backup API 取得一致的快照，伺服器運作中也能安全備份
        snapshot = Path(workdir) / "db.sqlite3"
        source = sqlite3.connect(database_path())
        destination = sqlite3.connect(snapshot)
        with destination:
            source.backup(destination)
        source.close()
        destination.close()

        file_count = 0
        partial = target.with_name(target.name + ".partial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(snapshot, arcname="db.sqlite3")
            if include_files and media_root.exists():
                # 備份目錄放在 MEDIA_ROOT 底下時要排除，避免把備份包進備份
                exclude = output_dir if media_root in output_dir.parents else None
                for path, relative in _media_files(media_root, exclude):
                    tar.add(path, arcname=f"files/{relative.as_posix()}")
                    file_count += 1
            manifest = json.dumps({
                "format": FORMAT_VERSION,
                "created": timezone.now().isoformat(),
                "files": file_count,
                "includes_files": include_files,
            }, ensure_ascii=False, indent=2).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest)
            info.mtime = int(timezone.now().timestamp())
            tar.addfile(info, fileobj=io.BytesIO(manifest))
        os.replace(partial, target)
    return target


def prune_backups(output_dir, keep):
    """只保留最新的 keep 份備份，回傳刪除的檔案。"""
    backups = sorted(Path(output_dir).glob(f"{PREFIX}*{SUFFIX}"))
    removed = backups[:-keep] if keep > 0 else []
    for path in removed:
        path.unlink()
    return removed


def read_manifest(archive):
    try:
        with tarfile.open(archive, "r:gz") as tar:
            member = tar.getmember("manifest.json")
            manifest = json.load(tar.extractfile(member))
            names = set(tar.getnames())
    except KeyError:
        raise BackupError("這不是 Cloud Disk 的備份檔（找不到 manifest.json）")
    except (tarfile.TarError, ValueError, OSError) as error:
        raise BackupError(f"無法讀取備份檔：{error}")
    if not isinstance(manifest, dict):
        raise BackupError("備份檔的 manifest.json 格式不正確")
    if manifest.get("format") != FORMAT_VERSION:
        raise BackupError(f"不支援的備份格式：{manifest.get('format')}")
    if "db.sqlite3" not in names:
        raise BackupError("備份檔缺少資料庫")
    return manifest


def restore_backup(archive):
    """還原備份。原本的資料庫與檔案會改名保留，回傳保留的位置。

    還原前請先停止伺服器。
    """
    manifest = read_manifest(archive)
    db_path = database_path()
    media_root = Path(settings.MEDIA_ROOT)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    kept = []

    media_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=media_root.parent) as workdir:
        workdir = Path(workdir)
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name not in ("db.sqlite3", "manifest.json") and \
                        not member.name.startswith("files/"):
                    raise BackupError(f"備份檔包含不預期的項目：{member.name}")
            # data 過濾器會拒絕絕對路徑、.. 與連結，避免解壓縮到預期以外的位置
            tar.extractall(workdir, filter="data")

        connections.close_all()
        if db_path.exists():
            old_db = db_path.with_name(f"{db_path.name}.before-restore-{stamp}")
            os.replace(db_path, old_db)
            kept.append(old_db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(workdir / "db.sqlite3", db_path)

        if manifest.get("includes_files", True):
            media_root.mkdir(parents=True, exist_ok=True)
            # 逐一搬移內容而不是整個目錄改名，MEDIA_ROOT 是掛載點時也能運作
            old_media = media_root.parent / f"{media_root.name}.before-restore-{stamp}"
            existing = list(media_root.iterdir())
            if existing:
                old_media.mkdir()
                for child in existing:
                    shutil.move(child, old_media / child.name)
                kept.append(old_media)
            restored = workdir / "files"
            if restored.exists():
                for child in restored.iterdir():
                    shutil.move(child, media_root / child.name)
    return manifest, kept
