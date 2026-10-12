import os
import shutil
import tempfile
import time
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import override_settings
from django.urls import reverse

from .. import health
from .base import StorageTestCase

PRODUCTION = dict(DEBUG=False, SECRET_URL_PREFIX="x8FqP2vM4wA1", ALLOW_REGISTRATION=True,
                  USE_HTTPS=False, TRUST_PROXY_HEADERS=False)
HARDENED = dict(DEBUG=False, SECRET_URL_PREFIX="my-own-prefix", ALLOW_REGISTRATION=False,
                USE_HTTPS=True, TRUST_PROXY_HEADERS=True)


class HealthEndpointTests(StorageTestCase):
    def get(self):
        response = self.client.get(reverse("storage:healthz"))
        return response, response.json()

    def test_healthy(self):
        response, data = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(set(data["checks"]), {"database", "storage", "disk"})
        self.assertIn("no-cache", response["Cache-Control"])

    def test_no_login_required_and_no_session(self):
        response, _ = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("sessionid", response.cookies)

    def test_unwritable_storage_is_error(self):
        blocker = Path(tempfile.mkdtemp()) / "not-a-directory"
        blocker.write_text("x")
        self.addCleanup(shutil.rmtree, blocker.parent, ignore_errors=True)
        with override_settings(MEDIA_ROOT=blocker / "files"):
            response, data = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(data["checks"]["storage"]["status"], "error")

    @override_settings(HEALTH_MIN_FREE_PERCENT=101)
    def test_low_disk_space_is_warning(self):
        response, data = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "warning")
        self.assertIn("空間快不夠", data["checks"]["disk"]["message"])

    def test_backup_age(self):
        backups = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, backups, ignore_errors=True)
        with override_settings(AUTO_BACKUP=True, BACKUP_DIR=backups,
                               HEALTH_MAX_BACKUP_AGE_HOURS=36):
            self.assertIn("還沒有任何備份", self.get()[1]["checks"]["backup"]["message"])

            archive = backups / "cloud-disk-20260101-000000.tar.gz"
            archive.write_bytes(b"x")
            self.assertEqual(self.get()[1]["checks"]["backup"]["status"], "ok")

            old = time.time() - 40 * 3600
            os.utime(archive, (old, old))
            data = self.get()[1]
            self.assertEqual(data["checks"]["backup"]["status"], "warning")
            self.assertEqual(data["status"], "warning")


class ConfigurationCheckTests(StorageTestCase):
    @override_settings(**PRODUCTION)
    def test_risky_production_settings_warn(self):
        codes = {code for code, _ in health.configuration_warnings()}
        self.assertEqual(codes, {"storage.W001", "storage.W002", "storage.W003"})

    @override_settings(**HARDENED)
    def test_hardened_settings_have_no_warnings(self):
        self.assertEqual(health.configuration_warnings(), [])

    @override_settings(DEBUG=True, SECRET_URL_PREFIX="x8FqP2vM4wA1")
    def test_development_is_not_checked(self):
        self.assertEqual(health.configuration_warnings(), [])

    @override_settings(**PRODUCTION)
    def test_deploy_check_reports_warnings(self):
        # 只有警告時 check 不會失敗；指定 --fail-level WARNING 時才會
        with self.assertRaises(SystemCheckError) as raised:
            call_command("check", "--deploy", "--fail-level", "WARNING", "--tag", "security")
        self.assertIn("storage.W001", str(raised.exception))

    @override_settings(**PRODUCTION)
    def test_banner_only_for_staff(self):
        self.client.force_login(self.alice)
        self.assertNotContains(self.client.get(reverse("storage:browse")), "設定提醒")
        self.alice.is_staff = True
        self.alice.save()
        self.assertContains(self.client.get(reverse("storage:browse")), "SECRET_URL_PREFIX")


class OffsiteHealthTests(StorageTestCase):
    def test_offsite_backup_age(self):
        backups = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, backups, ignore_errors=True)
        with override_settings(BACKUP_DIR=backups, BACKUP_COPY_DIR="/mnt/nas",
                               HEALTH_MAX_BACKUP_AGE_HOURS=36):
            data = self.client.get(reverse("storage:healthz")).json()
            self.assertIn("還沒有成功過", data["checks"]["offsite_backup"]["message"])

            marker = backups / ".last-offsite"
            marker.write_text("{}")
            data = self.client.get(reverse("storage:healthz")).json()
            self.assertEqual(data["checks"]["offsite_backup"]["status"], "ok")

            old = time.time() - 40 * 3600
            os.utime(marker, (old, old))
            data = self.client.get(reverse("storage:healthz")).json()
            self.assertEqual(data["checks"]["offsite_backup"]["status"], "warning")

    def test_not_checked_when_not_configured(self):
        data = self.client.get(reverse("storage:healthz")).json()
        self.assertNotIn("offsite_backup", data["checks"])
