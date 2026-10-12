from django.urls import reverse

from .base import StorageTestCase


class SecurityHeaderTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)

    def test_pages_have_strict_csp(self):
        response = self.client.get(reverse("storage:browse"))
        policy = response["Content-Security-Policy"]
        self.assertIn("script-src 'self'", policy)
        self.assertNotIn("unsafe-inline", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        # <style> 區塊帶有與標頭相同的 nonce
        nonce = policy.split("'nonce-")[1].split("'")[0]
        self.assertContains(response, f'<style nonce="{nonce}">')

    def test_templates_have_no_inline_scripts(self):
        stored = self.upload_as(self.alice)
        self.client.post(reverse("storage:delete_file", args=[stored.pk]))
        for url in (reverse("storage:browse") + "?view=list", reverse("storage:trash"),
                    reverse("storage:upload"), reverse("storage:security")):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn("onsubmit=", html)
                self.assertNotIn("<script>", html)
                self.assertNotIn(' style="', html)

    def test_preview_is_sandboxed(self):
        stored = self.upload_as(self.alice, ("notes.txt", b"<script>alert(1)</script>"))
        response = self.client.get(reverse("storage:preview_file", args=[stored.pk]))
        policy = response["Content-Security-Policy"]
        self.assertIn("default-src 'none'", policy)
        self.assertIn("sandbox", policy)
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_pdf_preview_not_sandboxed(self):
        # Chrome 的 PDF 閱讀器在 sandbox 中無法顯示
        stored = self.upload_as(self.alice, ("doc.pdf", b"%PDF-1.4"))
        response = self.client.get(reverse("storage:preview_file", args=[stored.pk]))
        self.assertNotIn("Content-Security-Policy", response)

    def test_clickjacking_protection(self):
        response = self.client.get(reverse("storage:browse"))
        self.assertEqual(response["X-Frame-Options"], "DENY")
