import re
from unittest import mock

from django.core import mail, signing
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from ..models import ActivityLog, UserProfile
from ..services import notifications
from .base import StorageTestCase

PASSWORD = "S3cure-pass-alice"
PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1"
DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"


def links(message):
    return re.findall(r"https?://\S+", message.body)


@override_settings(EMAIL_ENABLED=True)
class EmailTestCase(StorageTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def verify_email(self, user, email):
        user.email = email
        user.save()
        profile = UserProfile.for_user(user)
        profile.email_verified = True
        profile.save()

    def login(self, user_agent=DESKTOP, ip="10.0.0.1", password=PASSWORD):
        return self.client.post(
            reverse("storage:login"), {"username": "alice", "password": password},
            headers={"User-Agent": user_agent}, REMOTE_ADDR=ip,
        )


class EmailVerificationTests(EmailTestCase):
    def change_email(self, email, password=PASSWORD):
        self.client.force_login(self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("storage:change_email"),
                                    {"email": email, "password": password})

    def test_change_requires_password(self):
        self.change_email("new@example.com", password="wrong")
        self.assertEqual(len(mail.outbox), 0)

    def test_verification_flow(self):
        self.change_email("new@example.com")
        self.assertEqual(mail.outbox[0].to, ["new@example.com"])
        # 點連結前不會變更
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, "")

        self.client.logout()
        url = links(mail.outbox[0])[0]
        self.client.get(url.split("testserver")[1])
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, "new@example.com")
        self.assertTrue(UserProfile.for_user(self.alice).email_verified)
        self.assertTrue(ActivityLog.objects.filter(action="email_change").exists())

    def test_tampered_or_expired_link(self):
        token = signing.dumps({"user": self.alice.pk, "email": "x@example.com"},
                              salt="wrong-salt")
        response = self.client.get(reverse("storage:verify_email", args=[token]))
        self.assertEqual(response.status_code, 404)

        token = signing.dumps({"user": self.alice.pk, "email": "x@example.com"},
                              salt=notifications.VERIFY_SALT)
        self.client.force_login(self.alice)
        with mock.patch.object(notifications, "VERIFY_MAX_AGE", -1):
            response = self.client.get(reverse("storage:verify_email", args=[token]),
                                       follow=True)
        self.assertContains(response, "已過期")
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, "")

    def test_email_already_used_by_other_account(self):
        self.verify_email(self.bob, "shared@example.com")
        token = signing.dumps({"user": self.alice.pk, "email": "SHARED@example.com"},
                              salt=notifications.VERIFY_SALT)
        self.client.force_login(self.alice)
        response = self.client.get(reverse("storage:verify_email", args=[token]), follow=True)
        self.assertContains(response, "已經被其他帳號使用")

    def test_registration_sends_verification(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("storage:register"), {
                "username": "carol", "email": "carol@example.com",
                "password1": "Very-l0ng-passw0rd", "password2": "Very-l0ng-passw0rd",
            })
        self.assertEqual(mail.outbox[0].to, ["carol@example.com"])

    @override_settings(EMAIL_ENABLED=False)
    def test_disabled_when_email_not_configured(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("storage:change_email"),
                                    {"email": "a@example.com", "password": PASSWORD})
        self.assertEqual(response.status_code, 404)
        self.assertContains(self.client.get(reverse("storage:security")), "尚未設定寄信")


class NotificationTests(EmailTestCase):
    def setUp(self):
        super().setUp()
        self.verify_email(self.alice, "alice@example.com")

    def test_new_device_login(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.login(DESKTOP)               # 第一次登入不通知
            self.client.logout()
            self.login(DESKTOP)               # 同一個裝置不通知
            self.client.logout()
            self.login(PHONE, ip="10.0.0.2")  # 新裝置
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("新裝置登入", mail.outbox[0].subject)
        self.assertIn("10.0.0.2", mail.outbox[0].body)
        self.assertIn("iPhone", mail.outbox[0].body)

    def test_no_email_when_unverified_or_disabled(self):
        profile = UserProfile.for_user(self.alice)
        profile.notify_new_login = False
        profile.save()
        with self.captureOnCommitCallbacks(execute=True):
            self.login(DESKTOP)
            self.client.logout()
            self.login(PHONE, ip="10.0.0.2")
        self.assertEqual(len(mail.outbox), 0)

        profile.notify_new_login = True
        profile.email_verified = False
        profile.save()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.logout()
            self.login(PHONE, ip="10.0.0.3")
        self.assertEqual(len(mail.outbox), 0)

    def test_share_download_throttled(self):
        stored = self.upload_as(self.alice)
        self.client.post(reverse("storage:manage_shares", args=[stored.pk]),
                         {"expires_in_days": ""})
        token = stored.share_links.get().token
        self.client.logout()
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(3):
                self.client.get(reverse("storage:shared_download", args=[token]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("hello.txt", mail.outbox[0].subject)

    def test_quota_warning_sent_once_and_reset(self):
        profile = UserProfile.for_user(self.alice)
        profile.quota_bytes = 100
        profile.save()
        self.client.force_login(self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            self.upload(("a.bin", b"x" * 50))
            self.upload(("b.bin", b"y" * 45))   # 95%：寄出警告
            self.upload(("c.bin", b"z" * 2))    # 97%：已經寄過，不重複寄
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("95%", mail.outbox[0].body)

        # 刪掉檔案讓用量降到 80% 以下後，再次超過時會重新提醒
        for stored in self.alice.stored_files.all():
            self.client.post(reverse("storage:delete_file", args=[stored.pk]))
            self.client.post(reverse("storage:purge_file", args=[stored.pk]))
        with self.captureOnCommitCallbacks(execute=True):
            self.upload(("d.bin", b"d" * 10))   # 10%：重設
            self.upload(("e.bin", b"e" * 85))   # 95%：再次寄出
        self.assertEqual(len(mail.outbox), 2)

    def test_notification_settings(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("storage:notification_settings"),
                         {"notify_new_login": "on", "notify_quota": "on"})
        profile = UserProfile.for_user(self.alice)
        self.assertTrue(profile.notify_new_login)
        self.assertFalse(profile.notify_share_download)
        self.assertTrue(profile.notify_quota)

    def test_mail_failure_does_not_break_login(self):
        with override_settings(EMAIL_BACKEND="storage.tests.test_email.FailingBackend"), \
                self.assertLogs("storage.services.notifications", "ERROR") as logs:
            with self.captureOnCommitCallbacks(execute=True):
                self.login(DESKTOP)
                self.client.logout()
                response = self.login(PHONE, ip="10.0.0.2")
        self.assertEqual(response.status_code, 302)
        self.assertIn("寄送 Email 失敗", logs.output[0])


class FailingBackend:
    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise ConnectionRefusedError("SMTP 無法連線")


class PasswordResetTests(EmailTestCase):
    def request_reset(self, email):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("storage:password_reset"), {"email": email})

    def test_full_reset_flow(self):
        self.verify_email(self.alice, "alice@example.com")
        response = self.request_reset("alice@example.com")
        self.assertRedirects(response, reverse("storage:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

        path = links(mail.outbox[0])[0].split("testserver")[1]
        response = self.client.get(path, follow=True)
        set_url = response.redirect_chain[-1][0]
        response = self.client.post(set_url, {
            "new_password1": "Brand-new-passw0rd", "new_password2": "Brand-new-passw0rd",
        })
        self.assertRedirects(response, reverse("storage:password_reset_complete"))
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password("Brand-new-passw0rd"))
        self.assertTrue(ActivityLog.objects.filter(action="password_reset").exists())

        # 連結只能使用一次
        response = self.client.get(path, follow=True)
        self.assertContains(response, "連結無效")

    def test_unverified_email_gets_nothing(self):
        self.alice.email = "alice@example.com"
        self.alice.save()
        response = self.request_reset("alice@example.com")
        # 不透露信箱是否存在，一律顯示已寄出
        self.assertRedirects(response, reverse("storage:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(SITE_URL="https://disk.example.com")
    def test_link_uses_site_url_not_host_header(self):
        self.verify_email(self.alice, "alice@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("storage:password_reset"), {"email": "alice@example.com"})
        self.assertTrue(links(mail.outbox[0])[0].startswith("https://disk.example.com/"))

    @override_settings(PASSWORD_RESETS_PER_IP_PER_HOUR=2)
    def test_rate_limited(self):
        for _ in range(2):
            self.request_reset("nobody@example.com")
        self.assertEqual(self.request_reset("nobody@example.com").status_code, 429)

    def test_login_page_links_reset(self):
        self.assertContains(self.client.get(reverse("storage:login")), "忘記密碼")

    @override_settings(EMAIL_ENABLED=False)
    def test_reset_unavailable_without_email(self):
        self.assertEqual(self.client.get(reverse("storage:password_reset")).status_code, 404)
        self.assertNotContains(self.client.get(reverse("storage:login")), "忘記密碼")
