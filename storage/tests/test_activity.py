from datetime import timedelta
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from ..models import ActivityLog
from .base import StorageTestCase

Action = ActivityLog.Action
CHROME_ON_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class ActivityTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def login(self, password="S3cure-pass-alice", **headers):
        return self.client.post(
            reverse("storage:login"), {"username": "alice", "password": password},
            headers=headers, follow=True,
        )

    def actions(self, user):
        return list(ActivityLog.objects.filter(user=user).values_list("action", flat=True))

    def test_login_records_ip_and_device(self):
        self.login(**{"User-Agent": CHROME_ON_WINDOWS})
        log = ActivityLog.objects.get(action=Action.LOGIN)
        self.assertEqual(log.user, self.alice)
        self.assertEqual(log.ip, "127.0.0.1")
        self.assertEqual(log.device, "Chrome（Windows）")

    def test_failed_login_recorded_for_existing_and_unknown_users(self):
        self.login(password="wrong")
        self.client.post(reverse("storage:login"), {"username": "ghost", "password": "x"})
        self.assertEqual(self.actions(self.alice), [Action.LOGIN_FAILED])
        ghost = ActivityLog.objects.get(username="ghost")
        self.assertIsNone(ghost.user)

    def test_login_shows_previous_login_and_failures(self):
        self.login()
        self.client.post(reverse("storage:logout"))
        cache.clear()
        self.login(password="wrong")
        self.login(password="wrong")
        cache.clear()
        response = self.login()
        text = " ".join(str(m) for m in response.context["messages"])
        self.assertIn("上次登入", text)
        self.assertIn("2 次失敗的登入嘗試", text)

    def test_first_login_has_no_previous(self):
        response = self.login()
        text = " ".join(str(m) for m in response.context["messages"])
        self.assertNotIn("上次登入", text)

    def test_file_operations_recorded(self):
        stored = self.upload_as(self.alice, ("a.txt", b"1"))
        self.upload(("a.txt", b"2"))
        self.client.post(reverse("storage:delete_file", args=[stored.pk]))
        self.client.post(reverse("storage:restore_file", args=[stored.pk]))
        self.assertEqual(
            list(reversed(self.actions(self.alice))),
            [Action.UPLOAD, Action.UPDATE, Action.TRASH, Action.RESTORE],
        )
        self.assertTrue(all(log.target == "a.txt" for log in ActivityLog.objects.all()))

    def test_share_download_recorded_for_owner(self):
        stored = self.upload_as(self.alice, ("a.txt", b"1"))
        self.client.post(reverse("storage:manage_shares", args=[stored.pk]),
                         {"expires_in_days": ""})
        token = stored.share_links.get().token
        self.client.logout()
        self.client.get(reverse("storage:shared_download", args=[token]),
                        headers={"User-Agent": CHROME_ON_WINDOWS})
        log = ActivityLog.objects.get(action=Action.SHARE_DOWNLOAD)
        self.assertEqual(log.user, self.alice)
        self.assertEqual(log.device, "Chrome（Windows）")

    def test_activity_page_only_shows_own_logs(self):
        self.upload_as(self.bob, ("bob.txt", b"b"))
        self.upload_as(self.alice, ("alice.txt", b"a"))
        response = self.client.get(reverse("storage:activity_log"))
        self.assertContains(response, "alice.txt")
        self.assertNotContains(response, "bob.txt")

    def test_security_page_lists_recent_logins(self):
        self.login(password="wrong")
        cache.clear()
        self.login()
        response = self.client.get(reverse("storage:security"))
        self.assertEqual(len(response.context["recent_logins"]), 2)
        self.assertContains(response, "失敗")

    @override_settings(ACTIVITY_LOG_RETENTION_DAYS=180)
    def test_old_logs_purged(self):
        self.login()
        ActivityLog.objects.update(created_time=timezone.now() - timedelta(days=181))
        self.upload_as(self.alice, ("new.txt", b"1"))
        call_command("cleanup_storage", stdout=StringIO())
        self.assertEqual(self.actions(self.alice), [Action.UPLOAD])
