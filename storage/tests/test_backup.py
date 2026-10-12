import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

RCLONE = shutil.which("rclone")


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

    def manage(self, *args, stdin=None, expect_success=True, **env):
        result = subprocess.run(
            [sys.executable, "manage.py", *args],
            cwd=settings.BASE_DIR, env={**self.env, **env}, input=stdin,
            capture_output=True, text=True,
        )
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

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
        self.assertIn("已建立並驗證備份", output)
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

    def test_if_older_than_skips_recent_backup(self):
        self.manage("backup")
        output = self.manage("backup", "--if-older-than", "20")
        self.assertIn("略過", output)
        self.assertEqual(len(list(self.backups.glob("cloud-disk-*.tar.gz"))), 1)

        archive = next(self.backups.glob("cloud-disk-*.tar.gz"))
        old = time.time() - 21 * 3600
        os.utime(archive, (old, old))
        self.assertIn("已建立並驗證備份", self.manage("backup", "--if-older-than", "20"))

    def test_copy_to_directory(self):
        external = self.workdir / "external-disk"
        external.mkdir()
        for day in ("20260101", "20260102"):
            (external / f"cloud-disk-{day}-000000.tar.gz").write_bytes(b"old")
        output = self.manage("backup", "--copy-dir", str(external), "--offsite-keep", "2")
        self.assertIn("已複製到", output)
        copies = sorted(p.name for p in external.glob("cloud-disk-*.tar.gz"))
        self.assertEqual(len(copies), 2)
        self.assertNotIn("cloud-disk-20260101-000000.tar.gz", copies)
        local = next(self.backups.glob("cloud-disk-*.tar.gz"))
        self.assertEqual((external / local.name).read_bytes(), local.read_bytes())
        self.assertTrue((self.backups / ".last-offsite").exists())

    @skipUnless(RCLONE, "需要安裝 rclone")
    def test_copy_with_rclone(self):
        cloud = self.workdir / "cloud"
        cloud.mkdir()
        (cloud / "cloud-disk-20260101-000000.tar.gz").write_bytes(b"old")
        (cloud / "unrelated.txt").write_text("keep me")
        output = self.manage("backup", "--rclone-remote", f":local:{cloud}",
                             "--offsite-keep", "1", RCLONE_BINARY=RCLONE)
        self.assertIn("已上傳到", output)
        names = sorted(p.name for p in cloud.iterdir())
        local = next(self.backups.glob("cloud-disk-*.tar.gz"))
        # 只保留最新一份備份，其他不是備份的檔案不會被動到
        self.assertEqual(names, [local.name, "unrelated.txt"])

    def test_offsite_failure_is_reported(self):
        result = self.manage("backup", "--rclone-remote", "remote:somewhere",
                             expect_success=False, RCLONE_BINARY="/nonexistent/rclone")
        self.assertIn("找不到 rclone", result.stderr)
        # 本機備份仍然完成，但不會記錄成異地備份成功
        self.assertEqual(len(list(self.backups.glob("cloud-disk-*.tar.gz"))), 1)
        self.assertFalse((self.backups / ".last-offsite").exists())

    def test_verify_detects_corrupted_backup(self):
        self.manage("backup")
        archive = next(self.backups.glob("cloud-disk-*.tar.gz"))
        data = archive.read_bytes()
        archive.write_bytes(data[: len(data) // 2])
        result = self.manage("shell", "-c",
                             "from storage.services import backup\n"
                             f"backup.verify_backup({str(archive)!r})",
                             expect_success=False)
        self.assertIn("BackupError", result.stderr)
        # restore 指令也要顯示清楚的錯誤，而不是 traceback
        result = self.manage("restore", str(archive), "--yes", expect_success=False)
        self.assertIn("無法讀取備份檔", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
