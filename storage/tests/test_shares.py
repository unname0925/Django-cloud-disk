from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from ..models import ShareLink
from .base import StorageTestCase


class ShareLinkTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.stored = self.upload_as(self.alice)

    def create_link(self, days="7"):
        self.client.post(
            reverse("storage:manage_shares", args=[self.stored.pk]), {"expires_in_days": days}
        )
        return ShareLink.objects.latest("pk")

    def test_create_link_with_expiry(self):
        link = self.create_link("7")
        self.assertAlmostEqual(
            link.expires_time, timezone.now() + timedelta(days=7), delta=timedelta(minutes=1)
        )
        self.assertIsNone(self.create_link("").expires_time)

    def test_anonymous_can_download_and_count_increments(self):
        link = self.create_link()
        self.client.logout()

        page = self.client.get(reverse("storage:shared_file", args=[link.token]))
        self.assertContains(page, "hello.txt")

        response = self.client.get(reverse("storage:shared_download", args=[link.token]))
        self.assertEqual(b"".join(response.streaming_content), b"hello world")
        link.refresh_from_db()
        self.assertEqual(link.download_count, 1)

    def test_expired_link_is_404(self):
        link = self.create_link()
        link.expires_time = timezone.now() - timedelta(seconds=1)
        link.save()
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("storage:shared_file", args=[link.token])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("storage:shared_download", args=[link.token])).status_code,
            404,
        )

    def test_unknown_token_is_404(self):
        response = self.client.get(reverse("storage:shared_file", args=["nope"]))
        self.assertEqual(response.status_code, 404)

    def test_revoke(self):
        link = self.create_link()
        self.client.post(reverse("storage:revoke_share", args=[link.pk]))
        self.assertFalse(ShareLink.objects.exists())

    def test_other_user_cannot_revoke(self):
        link = self.create_link()
        self.client.force_login(self.bob)
        response = self.client.post(reverse("storage:revoke_share", args=[link.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ShareLink.objects.exists())

    def test_link_disabled_while_file_in_trash(self):
        link = self.create_link()
        self.client.post(reverse("storage:delete_file", args=[self.stored.pk]))
        self.client.logout()
        url = reverse("storage:shared_download", args=[link.token])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_link_removed_when_file_purged(self):
        self.create_link()
        self.client.post(reverse("storage:delete_file", args=[self.stored.pk]))
        self.client.post(reverse("storage:purge_file", args=[self.stored.pk]))
        self.assertFalse(ShareLink.objects.exists())
