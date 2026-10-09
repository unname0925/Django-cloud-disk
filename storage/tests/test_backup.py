import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class BackupRestoreTests(SimpleTestCase):
    """在獨立的資料庫與檔案目錄中實際執行 backup / restore 指令。"""

    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)
        self.media = self.workdir / "files"
        self.backups = self.workdir / "backups"
        self.env = {
            **os.environ,
            "DEBUG": "True",
            "DATABASE_PATH": str(self.workdir / "db.sqlite3"),
            "MEDIA_ROOT": str(self.media),
            "BACKUP_DIR": str(self.backups),
        }
        self.manage("migrate", "-v0")

    def manage(self, *args, stdin=None):
        result = subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=settings.BASE_DIR, env=self.env, input=stdin,
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def shell(self, code):
        return self.manage("shell", "-c", code).strip().splitlines()[-1]

    def test_backup_and_restore(self):
        self.shell(
            "from django.contrib.auth.models import User\n"
            "from django.core.files.base import ContentFile\n"
            "from storage.models import StoredFile\n"
            "u = User.objects.create_user('alice', password='x')\n"
            "StoredFile.objects.create(owner=u, original_name='a.txt', file_size=5,"
            " file=ContentFile(b'hello', name='a.txt'))\n"
            "print('ok')"
        )
        (self.media / "tmp_uploads").mkdir(parents=True, exist_ok=True)
        (self.media / "tmp_uploads" / "skip.part").write_bytes(b"partial")

        output = self.manage("backup")
        self.assertIn("已建立備份", output)
        archive = next(self.backups.glob("cloud-disk-*.tar.gz"))
        with tarfile.open(archive) as tar:
            names = tar.getnames()
        self.assertIn("db.sqlite3", names)
        self.assertTrue(any(n.startswith("files/users/") for n in names))
        self.assertFalse(any("tmp_uploads" in n for n in names))

        # 備份後資料被誤刪
        self.shell("from django.contrib.auth.models import User\n"
                   "User.objects.all().delete(); print('deleted')")
        shutil.rmtree(self.media / "users")

        output = self.manage("restore", str(archive), "--yes")
        self.assertIn("還原完成", output)
        restored = self.shell(
            "from storage.models import StoredFile\n"
            "f = StoredFile.objects.get(); print(f.owner.username, f.file.read().decode())"
        )
        self.assertEqual(restored, "alice hello")
        # 還原前的資料改名保留
        self.assertTrue(list(self.workdir.glob("db.sqlite3.before-restore-*")))

    def test_restore_requires_confirmation(self):
        self.manage("backup")
        archive = next(self.backups.glob("cloud-disk-*.tar.gz"))
        result = subprocess.run(
            [sys.executable, "manage.py", "restore", str(archive)],
            cwd=settings.BASE_DIR, env=self.env, input="no\n", capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("已取消", result.stderr)
        self.assertFalse(list(self.workdir.glob("db.sqlite3.before-restore-*")))

    def test_keep_prunes_old_backups(self):
        self.backups.mkdir()
        for day in ("20260101", "20260102", "20260103"):
            (self.backups / f"cloud-disk-{day}-000000.tar.gz").write_bytes(b"old")
        self.manage("backup", "--keep", "2")
        remaining = sorted(p.name for p in self.backups.glob("cloud-disk-*.tar.gz"))
        self.assertEqual(len(remaining), 2)
        self.assertEqual(remaining[0], "cloud-disk-20260103-000000.tar.gz")

    def test_rejects_unexpected_archive(self):
        bad = self.workdir / "bad.tar.gz"
        with tarfile.open(bad, "w:gz") as tar:
            evil = self.workdir / "evil.txt"
            evil.write_text("x")
            tar.add(evil, arcname="manifest.json")
        result = subprocess.run(
            [sys.executable, "manage.py", "restore", str(bad), "--yes"],
            cwd=settings.BASE_DIR, env=self.env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("無法讀取備份檔", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
