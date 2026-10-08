from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from ..models import UserProfile
from .base import StorageTestCase


class RegisterTests(StorageTestCase):
    def test_profile_created_for_new_user(self):
        self.assertTrue(UserProfile.objects.filter(user=self.alice).exists())

    def test_register_and_login(self):
        response = self.client.post(reverse("storage:register"), {
            "username": "carol",
            "password1": "Very-l0ng-passw0rd",
            "password2": "Very-l0ng-passw0rd",
        })
        self.assertRedirects(response, reverse("storage:browse"))
        self.assertTrue(User.objects.filter(username="carol").exists())

    def test_weak_password_rejected(self):
        response = self.client.post(reverse("storage:register"), {
            "username": "carol",
            "password1": "123",
            "password2": "123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="carol").exists())

    @override_settings(ALLOW_REGISTRATION=False)
    def test_registration_can_be_disabled(self):
        self.assertEqual(self.client.get(reverse("storage:register")).status_code, 404)
        self.assertNotContains(self.client.get(reverse("storage:login")), "註冊")


@override_settings(LOGIN_MAX_ATTEMPTS=3)
class LoginTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def login(self, password, **extra):
        return self.client.post(
            reverse("storage:login"), {"username": "alice", "password": password, **extra}
        )

    def test_login_success(self):
        response = self.login("S3cure-pass-alice")
        self.assertRedirects(response, reverse("storage:browse"))

    def test_login_redirects_to_safe_next(self):
        target = reverse("storage:upload")
        response = self.login("S3cure-pass-alice", next=target)
        self.assertRedirects(response, target)

    def test_login_ignores_external_next(self):
        response = self.login("S3cure-pass-alice", next="https://evil.example.com/")
        self.assertRedirects(response, reverse("storage:browse"))

    def test_lockout_after_too_many_failures(self):
        for _ in range(3):
            self.login("wrong")
        # 鎖定期間即使密碼正確也無法登入
        response = self.login("S3cure-pass-alice")
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_success_resets_failure_count(self):
        self.login("wrong")
        self.login("wrong")
        self.login("S3cure-pass-alice")
        self.client.logout()
        self.login("wrong")
        self.login("wrong")
        response = self.login("S3cure-pass-alice")
        self.assertEqual(response.status_code, 302)

    def test_logout_requires_post(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("storage:logout")).status_code, 405)
        self.client.post(reverse("storage:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_required(self):
        response = self.client.get(reverse("storage:browse"))
        self.assertRedirects(
            response, f"{reverse('storage:login')}?next={reverse('storage:browse')}"
        )


@override_settings(LOGIN_MAX_ATTEMPTS=2)
class ProxyIpTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def fail_login(self, forwarded_for):
        return self.client.post(
            reverse("storage:login"),
            {"username": "alice", "password": "wrong"},
            HTTP_X_FORWARDED_FOR=forwarded_for,
        )

    @override_settings(TRUST_PROXY_HEADERS=True)
    def test_lockout_uses_forwarded_ip_behind_proxy(self):
        self.fail_login("1.1.1.1")
        self.fail_login("1.1.1.1")
        self.assertEqual(self.fail_login("1.1.1.1").status_code, 429)
        # 另一個真實 IP 不受影響
        self.assertEqual(self.fail_login("2.2.2.2").status_code, 200)

    @override_settings(TRUST_PROXY_HEADERS=False)
    def test_forwarded_header_ignored_without_proxy(self):
        # 沒有反向代理時，偽造 X-Forwarded-For 不能繞過鎖定
        self.fail_login("1.1.1.1")
        self.fail_login("2.2.2.2")
        self.assertEqual(self.fail_login("3.3.3.3").status_code, 429)
