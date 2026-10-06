from django.test import override_settings
from django.urls import reverse

from ..models import Folder, StoredFile, UserProfile
from .base import StorageTestCase


class UploadTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)

    def test_upload_stores_file_in_user_folder(self):
        response = self.upload()
        self.assertRedirects(response, reverse("storage:browse"))

        stored = StoredFile.objects.get(owner=self.alice)
        self.assertEqual(stored.original_name, "hello.txt")
        self.assertEqual(stored.file_size, 11)
        self.assertIn(str(self.alice.profile.folder_uuid), stored.file.name)

    def test_upload_multiple_files_into_folder(self):
        folder = Folder.objects.create(owner=self.alice, name="docs")
        response = self.upload(("a.txt", b"a"), ("b.txt", b"bb"), folder=folder)
        self.assertRedirects(response, reverse("storage:browse_folder", args=[folder.pk]))
        self.assertEqual(folder.files.count(), 2)

    def test_cannot_upload_into_other_users_folder(self):
        bobs_folder = Folder.objects.create(owner=self.bob, name="bob")
        response = self.upload(folder=bobs_folder)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StoredFile.objects.exists())

    @override_settings(STORAGE_MAX_UPLOAD_SIZE=10)
    def test_file_size_limit(self):
        response = self.upload(("big.bin", b"x" * 11))
        self.assertContains(response, "超過單檔上限")
        self.assertFalse(StoredFile.objects.exists())

    def test_quota_limit(self):
        profile = UserProfile.for_user(self.alice)
        profile.quota_bytes = 15
        profile.save()
        self.upload(("a.txt", b"x" * 10))
        response = self.upload(("b.txt", b"x" * 10))
        self.assertContains(response, "容量不足")
        self.assertEqual(StoredFile.objects.count(), 1)

    def test_upload_without_profile(self):
        UserProfile.objects.filter(user=self.alice).delete()
        self.upload()
        self.assertEqual(StoredFile.objects.filter(owner=self.alice).count(), 1)


class BrowseTests(StorageTestCase):
    def test_shows_size_time_and_usage(self):
        stored = self.upload_as(self.alice)
        response = self.client.get(reverse("storage:browse"))
        self.assertContains(response, "hello.txt")
        self.assertContains(response, "11\xa0位元組")
        self.assertContains(response, stored.uploaded_time.strftime("%Y-%m-%d"))
        self.assertEqual(response.context["used_bytes"], 11)

    def test_only_lists_own_files(self):
        self.upload_as(self.alice, ("alice.txt", b"a"))
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(reverse("storage:browse")), "alice.txt")

    def test_search_across_folders(self):
        folder = Folder.objects.create(owner=self.alice, name="photos")
        self.upload_as(self.alice, ("trip.jpg", b"1"), folder=folder)
        self.upload_as(self.alice, ("notes.txt", b"2"))
        response = self.client.get(reverse("storage:browse"), {"q": "TRIP"})
        names = [f.original_name for f in response.context["files"]]
        self.assertEqual(names, ["trip.jpg"])

    def test_sort_by_size(self):
        self.upload_as(self.alice, ("small.txt", b"1"), ("big.txt", b"12345"))
        response = self.client.get(reverse("storage:browse"), {"sort": "-size"})
        names = [f.original_name for f in response.context["files"]]
        self.assertEqual(names, ["big.txt", "small.txt"])

    def test_invalid_sort_falls_back_to_default(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("storage:browse"), {"sort": "password"})
        self.assertEqual(response.status_code, 200)


class FileActionTests(StorageTestCase):
    def test_download_own_file(self):
        stored = self.upload_as(self.alice)
        response = self.client.get(reverse("storage:download_file", args=[stored.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"hello world")

    def test_other_user_gets_404_everywhere(self):
        stored = self.upload_as(self.alice)
        self.client.force_login(self.bob)
        for name in ("download_file", "preview_file", "rename_file", "move_file",
                     "delete_file", "manage_shares"):
            with self.subTest(view=name):
                url = reverse(f"storage:{name}", args=[stored.pk])
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(StoredFile.objects.filter(pk=stored.pk).exists())

    def test_download_missing_file_returns_404(self):
        stored = self.upload_as(self.alice)
        stored.file.storage.delete(stored.file.name)
        response = self.client.get(reverse("storage:download_file", args=[stored.pk]))
        self.assertEqual(response.status_code, 404)

    def test_preview_image_inline(self):
        stored = self.upload_as(self.alice, ("cat.png", b"\x89PNG"))
        response = self.client.get(reverse("storage:preview_file", args=[stored.pk]))
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("inline", response["Content-Disposition"])

    def test_preview_html_falls_back_to_download(self):
        stored = self.upload_as(self.alice, ("page.html", b"<script>alert(1)</script>"))
        response = self.client.get(reverse("storage:preview_file", args=[stored.pk]))
        self.assertRedirects(
            response, reverse("storage:download_file", args=[stored.pk]),
            fetch_redirect_response=False,
        )

    def test_rename(self):
        stored = self.upload_as(self.alice)
        self.client.post(reverse("storage:rename_file", args=[stored.pk]), {"name": "new.txt"})
        stored.refresh_from_db()
        self.assertEqual(stored.original_name, "new.txt")

    def test_rename_rejects_slash(self):
        stored = self.upload_as(self.alice)
        response = self.client.post(
            reverse("storage:rename_file", args=[stored.pk]), {"name": "../x.txt"}
        )
        self.assertEqual(response.status_code, 200)
        stored.refresh_from_db()
        self.assertEqual(stored.original_name, "hello.txt")

    def test_move_to_own_folder(self):
        stored = self.upload_as(self.alice)
        folder = Folder.objects.create(owner=self.alice, name="docs")
        self.client.post(reverse("storage:move_file", args=[stored.pk]), {"folder": folder.pk})
        stored.refresh_from_db()
        self.assertEqual(stored.folder, folder)

    def test_cannot_move_into_other_users_folder(self):
        stored = self.upload_as(self.alice)
        bobs_folder = Folder.objects.create(owner=self.bob, name="bob")
        self.client.post(
            reverse("storage:move_file", args=[stored.pk]), {"folder": bobs_folder.pk}
        )
        stored.refresh_from_db()
        self.assertIsNone(stored.folder)

    def test_delete_removes_file_from_disk(self):
        stored = self.upload_as(self.alice)
        name, storage = stored.file.name, stored.file.storage
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("storage:delete_file", args=[stored.pk]))
        self.assertRedirects(response, reverse("storage:browse"))
        self.assertFalse(StoredFile.objects.filter(pk=stored.pk).exists())
        self.assertFalse(storage.exists(name))

    def test_deleting_user_removes_files_from_disk(self):
        stored = self.upload_as(self.alice)
        name, storage = stored.file.name, stored.file.storage
        with self.captureOnCommitCallbacks(execute=True):
            self.alice.delete()
        self.assertFalse(storage.exists(name))
