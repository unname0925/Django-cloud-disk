import io
import zipfile
from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from ..models import Folder, ShareLink
from .base import StorageTestCase


class FileShareTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.stored = self.upload_as(self.alice)

    def create_link(self, **data):
        payload = {"expires_in_days": "7", "password": "", "max_downloads": ""}
        payload.update(data)
        self.client.post(reverse("storage:manage_shares", args=[self.stored.pk]), payload)
        return ShareLink.objects.latest("pk")

    def anonymous_get(self, name, link, *args):
        self.client.logout()
        return self.client.get(reverse(f"storage:{name}", args=[link.token, *args]))

    def test_create_link_with_expiry(self):
        link = self.create_link(expires_in_days="7")
        self.assertEqual(link.owner, self.alice)
        self.assertAlmostEqual(
            link.expires_time, timezone.now() + timedelta(days=7), delta=timedelta(minutes=1)
        )
        self.assertIsNone(self.create_link(expires_in_days="").expires_time)

    def test_anonymous_can_download_and_count_increments(self):
        link = self.create_link()
        self.assertContains(self.anonymous_get("shared_file", link), "hello.txt")
        response = self.client.get(reverse("storage:shared_download", args=[link.token]))
        self.assertEqual(b"".join(response.streaming_content), b"hello world")
        link.refresh_from_db()
        self.assertEqual(link.download_count, 1)

    def test_expired_link_is_gone(self):
        link = self.create_link()
        ShareLink.objects.filter(pk=link.pk).update(
            expires_time=timezone.now() - timedelta(seconds=1)
        )
        self.assertContains(self.anonymous_get("shared_file", link), "已過期", status_code=410)
        self.assertEqual(self.anonymous_get("shared_download", link).status_code, 410)

    def test_unknown_token_is_404(self):
        response = self.client.get(reverse("storage:shared_file", args=["nope"]))
        self.assertEqual(response.status_code, 404)

    def test_download_limit(self):
        link = self.create_link(max_downloads="2")
        for _ in range(2):
            self.assertEqual(self.anonymous_get("shared_download", link).status_code, 200)
        response = self.anonymous_get("shared_download", link)
        self.assertContains(response, "下載次數上限", status_code=410)
        link.refresh_from_db()
        self.assertEqual(link.download_count, 2)

    def test_password_required(self):
        link = self.create_link(password="open-sesame")
        self.assertTrue(link.has_password)
        self.assertNotEqual(link.password_hash, "open-sesame")

        page = self.anonymous_get("shared_file", link)
        self.assertContains(page, "需要密碼")
        self.assertNotContains(page, "hello.txt")
        # 未解鎖時直接打下載網址會被導回密碼頁
        download = self.client.get(reverse("storage:shared_download", args=[link.token]))
        self.assertRedirects(download, reverse("storage:shared_file", args=[link.token]))

        url = reverse("storage:shared_file", args=[link.token])
        self.assertContains(self.client.post(url, {"password": "wrong"}), "密碼不正確")
        self.assertRedirects(self.client.post(url, {"password": "open-sesame"}), url)
        response = self.client.get(reverse("storage:shared_download", args=[link.token]))
        self.assertEqual(b"".join(response.streaming_content), b"hello world")

    def test_password_attempts_are_limited(self):
        link = self.create_link(password="open-sesame")
        self.client.logout()
        url = reverse("storage:shared_file", args=[link.token])
        for _ in range(5):
            self.client.post(url, {"password": "wrong"})
        response = self.client.post(url, {"password": "open-sesame"})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn(f"share-unlocked:{link.pk}", self.client.session)

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

    def test_my_shares_lists_only_own_links(self):
        self.create_link()
        bobs_file = self.upload_as(self.bob, ("bob.txt", b"b"))
        self.client.post(reverse("storage:manage_shares", args=[bobs_file.pk]),
                         {"expires_in_days": ""})
        response = self.client.get(reverse("storage:my_shares"))
        self.assertContains(response, "bob.txt")
        self.assertNotContains(response, "hello.txt")

    def test_link_disabled_while_file_in_trash(self):
        link = self.create_link()
        self.client.post(reverse("storage:delete_file", args=[self.stored.pk]))
        self.assertEqual(self.anonymous_get("shared_download", link).status_code, 410)

    def test_link_removed_when_file_purged(self):
        self.create_link()
        self.client.post(reverse("storage:delete_file", args=[self.stored.pk]))
        self.client.post(reverse("storage:purge_file", args=[self.stored.pk]))
        self.assertFalse(ShareLink.objects.exists())


class FolderShareTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)
        self.parent = Folder.objects.create(owner=self.alice, name="parent")
        self.shared = Folder.objects.create(owner=self.alice, parent=self.parent, name="trip")
        self.sub = Folder.objects.create(owner=self.alice, parent=self.shared, name="day1")
        self.outside = self.upload_as(self.alice, ("secret.txt", b"s"), folder=self.parent)
        self.inside = self.upload_as(self.alice, ("a.jpg", b"A"), folder=self.shared)
        self.deep = self.upload_as(self.alice, ("b.jpg", b"B"), folder=self.sub)
        self.client.post(reverse("storage:manage_folder_shares", args=[self.shared.pk]),
                         {"expires_in_days": "", "max_downloads": ""})
        self.link = ShareLink.objects.get()
        self.client.logout()

    def url(self, name, *args):
        return reverse(f"storage:{name}", args=[self.link.token, *args])

    def test_browse_shared_folder(self):
        response = self.client.get(self.url("shared_file"))
        self.assertContains(response, "a.jpg")
        self.assertContains(response, "day1")
        self.assertNotContains(response, "secret.txt")
        # 麵包屑只顯示分享範圍內的資料夾
        self.assertNotContains(response, ">parent<")

        sub = self.client.get(self.url("shared_subfolder", self.sub.pk))
        self.assertContains(sub, "b.jpg")
        self.assertEqual(sub.context["breadcrumbs"], [self.shared, self.sub])

    def test_download_file_inside_share(self):
        response = self.client.get(self.url("shared_folder_file", self.deep.pk))
        self.assertEqual(b"".join(response.streaming_content), b"B")

    def test_cannot_escape_shared_folder(self):
        self.assertEqual(
            self.client.get(self.url("shared_subfolder", self.parent.pk)).status_code, 404
        )
        self.assertEqual(
            self.client.get(self.url("shared_folder_file", self.outside.pk)).status_code, 404
        )
        bobs = self.upload_as(self.bob, ("bob.txt", b"b"))
        self.client.logout()
        self.assertEqual(
            self.client.get(self.url("shared_folder_file", bobs.pk)).status_code, 404
        )

    def test_trashed_items_hidden(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("storage:delete_folder", args=[self.sub.pk]))
        self.client.logout()
        self.assertNotContains(self.client.get(self.url("shared_file")), "day1")
        self.assertEqual(
            self.client.get(self.url("shared_folder_file", self.deep.pk)).status_code, 404
        )

    def test_zip_whole_share(self):
        response = self.client.get(self.url("shared_download"))
        zf = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        self.assertEqual(set(zf.namelist()), {"a.jpg", "day1/", "day1/b.jpg"})
        self.link.refresh_from_db()
        self.assertEqual(self.link.download_count, 1)

    def test_link_gone_when_folder_trashed(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("storage:delete_folder", args=[self.shared.pk]))
        self.client.logout()
        self.assertEqual(self.client.get(self.url("shared_file")).status_code, 410)
