import time

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from ..models import RecoveryCode, UserProfile
from ..services import twofactor
from .base import StorageTestCase

PASSWORD = "S3cure-pass-alice"


def code_for(user, offset=1):
    # 預設用下一個時間區段：啟用時輸入的那組碼所在的區段已經算用過了
    secret = UserProfile.for_user(user).totp_secret
    return twofactor.totp(secret, twofactor.current_step() + offset)


class TotpTests(StorageTestCase):
    def test_rfc6238_vector(self):
        # RFC 6238 附錄 B（SHA1），取末 6 碼
        import base64
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(twofactor.totp(secret, 59 // 30), "287082")
        self.assertEqual(twofactor.totp(secret, 1111111109 // 30), "081804")

    def test_window_and_replay(self):
        secret = twofactor.generate_secret()
        now = time.time()
        step = twofactor.current_step(now)
        self.assertEqual(twofactor.match_step(secret, twofactor.totp(secret, step - 1), now=now),
                         step - 1)
        self.assertIsNone(twofactor.match_step(secret, twofactor.totp(secret, step - 2), now=now))
        # 已經用過的時間區段不再接受
        self.assertIsNone(
            twofactor.match_step(secret, twofactor.totp(secret, step), last_step=step, now=now)
        )


class TwoFactorFlowTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def enable_for_alice(self):
        self.client.force_login(self.alice)
        self.client.get(reverse("storage:two_factor_setup"))
        secret = self.client.session["pending_2fa_secret"]
        code = twofactor.totp(secret, twofactor.current_step())
        response = self.client.post(reverse("storage:two_factor_setup"), {"code": code})
        self.client.logout()
        cache.clear()
        return response.context["codes"]

    def login(self, password=PASSWORD):
        return self.client.post(reverse("storage:login"),
                                {"username": "alice", "password": password})

    def test_setup_shows_qr_and_requires_valid_code(self):
        self.client.force_login(self.alice)
        page = self.client.get(reverse("storage:two_factor_setup"))
        self.assertContains(page, "<svg")
        response = self.client.post(reverse("storage:two_factor_setup"), {"code": "000000"})
        self.assertContains(response, "驗證碼不正確")
        self.assertFalse(UserProfile.for_user(self.alice).totp_enabled)

    def test_enable_creates_recovery_codes(self):
        codes = self.enable_for_alice()
        self.assertEqual(len(codes), 10)
        self.assertTrue(UserProfile.for_user(self.alice).totp_enabled)
        # 資料庫只存雜湊
        stored = set(RecoveryCode.objects.values_list("code_hash", flat=True))
        self.assertFalse(stored & set(codes))

    def test_login_requires_code(self):
        self.enable_for_alice()
        response = self.login()
        self.assertRedirects(response, reverse("storage:login_verify"))
        # 只輸入密碼還沒有登入
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("storage:browse")).status_code, 302)

        response = self.client.post(reverse("storage:login_verify"),
                                    {"code": code_for(self.alice)})
        self.assertRedirects(response, reverse("storage:browse"))
        self.assertEqual(self.client.get(reverse("storage:browse")).status_code, 200)

    def test_same_code_cannot_be_reused(self):
        self.enable_for_alice()
        code = code_for(self.alice, offset=1)
        self.login()
        self.client.post(reverse("storage:login_verify"), {"code": code})
        self.client.logout()
        self.login()
        response = self.client.post(reverse("storage:login_verify"), {"code": code})
        self.assertContains(response, "驗證碼不正確")

    def test_recovery_code_works_once(self):
        codes = self.enable_for_alice()
        self.login()
        self.client.post(reverse("storage:login_verify"), {"code": codes[0].upper()})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        self.login()
        response = self.client.post(reverse("storage:login_verify"), {"code": codes[0]})
        self.assertContains(response, "驗證碼不正確")
        self.assertEqual(twofactor.remaining_recovery_codes(self.alice), 9)

    def test_pending_login_expires(self):
        self.enable_for_alice()
        self.login()
        session = self.client.session
        session["pending_2fa_login"]["started"] -= 600
        session.save()
        response = self.client.post(reverse("storage:login_verify"),
                                    {"code": code_for(self.alice)})
        self.assertRedirects(response, reverse("storage:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verify_without_password_step_redirects(self):
        response = self.client.get(reverse("storage:login_verify"))
        self.assertRedirects(response, reverse("storage:login"))

    @override_settings(LOGIN_MAX_ATTEMPTS=3)
    def test_wrong_codes_lock_out(self):
        self.enable_for_alice()
        self.login()
        for _ in range(3):
            response = self.client.post(reverse("storage:login_verify"), {"code": "000000"})
        self.assertEqual(response.status_code, 429)
        # 鎖定後需要重新輸入密碼，而且在鎖定期間無法登入
        self.assertNotIn("pending_2fa_login", self.client.session)
        self.assertEqual(self.login().status_code, 429)

    def test_disable_requires_password_and_code(self):
        self.enable_for_alice()
        self.client.force_login(self.alice)
        url = reverse("storage:two_factor_disable")
        self.client.post(url, {"password": "wrong", "code": code_for(self.alice)})
        self.assertTrue(UserProfile.for_user(self.alice).totp_enabled)
        self.client.post(url, {"password": PASSWORD, "code": code_for(self.alice)})
        self.assertFalse(UserProfile.for_user(self.alice).totp_enabled)
        self.assertFalse(RecoveryCode.objects.exists())

    def test_regenerate_recovery_codes(self):
        old = self.enable_for_alice()
        self.client.force_login(self.alice)
        response = self.client.post(reverse("storage:recovery_codes_regenerate"),
                                    {"code": code_for(self.alice)})
        new = response.context["codes"]
        self.assertFalse(set(old) & set(new))
        self.client.logout()
        self.login()
        response = self.client.post(reverse("storage:login_verify"), {"code": old[0]})
        self.assertContains(response, "驗證碼不正確")

    def test_admin_login_goes_through_site_login(self):
        response = self.client.get("/x8FqP2vM4wA1/admin/login/?next=/x8FqP2vM4wA1/admin/")
        self.assertRedirects(
            response, reverse("storage:login") + "?next=/x8FqP2vM4wA1/admin/",
            fetch_redirect_response=False,
        )

    def test_change_password(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("storage:security"), {
            "old_password": PASSWORD,
            "new_password1": "Another-l0ng-pass",
            "new_password2": "Another-l0ng-pass",
        })
        self.assertRedirects(response, reverse("storage:security"))
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password("Another-l0ng-pass"))
        # 目前的登入保持有效
        self.assertEqual(self.client.get(reverse("storage:browse")).status_code, 200)
