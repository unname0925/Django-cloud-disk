from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from ..models import FileVersion, Folder, StoredFile, UserProfile
from .base import StorageTestCase


class VersionTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)

    def read(self, field_file):
        with field_file.open("rb") as fh:
            return fh.read()

    def test_same_name_creates_version(self):
        self.upload(("report.txt", b"v1"))
        response = self.client.post(reverse("storage:upload"),
                                    {"files": [SimpleUploadedFile("report.txt", b"v2")]},
                                    follow=True)
        self.assertContains(response, "舊版本已保留")

        stored = StoredFile.objects.get()
        self.assertEqual(self.read(stored.file), b"v2")
        version = stored.versions.get()
        self.assertEqual(self.read(version.file), b"v1")
        self.assertEqual(UserProfile.for_user(self.alice).used_bytes, 4)

    def test_same_name_in_other_folder_is_separate_file(self):
        folder = Folder.objects.create(owner=self.alice, name="docs")
        self.upload(("report.txt", b"v1"))
        self.upload(("report.txt", b"v2"), folder=folder)
        self.assertEqual(StoredFile.objects.count(), 2)
        self.assertFalse(FileVersion.objects.exists())

    def test_identical_content_does_not_create_version(self):
        self.upload(("report.txt", b"same"))
        response = self.client.post(reverse("storage:upload"),
                                    {"files": [SimpleUploadedFile("report.txt", b"same")]},
                                    follow=True)
        self.assertContains(response, "沒有建立新版本")
        self.assertFalse(FileVersion.objects.exists())

    @override_settings(STORAGE_CHUNK_SIZE=8)
    def test_chunked_upload_creates_version(self):
        self.upload(("big.bin", b"old"))
        session = self.client.post(reverse("storage:start_upload"),
                                   {"name": "big.bin", "size": 3}).json()["id"]
        data = self.client.post(reverse("storage:upload_session", args=[session]),
                                {"offset": 0, "chunk": SimpleUploadedFile("c", b"new")}).json()
        self.assertEqual(data["outcome"], "updated")
        stored = StoredFile.objects.get()
        self.assertEqual(self.read(stored.file), b"new")
        self.assertEqual(self.read(stored.versions.get().file), b"old")

    def test_restore_swaps_contents(self):
        self.upload(("report.txt", b"v1"))
        self.upload(("report.txt", b"v2"))
        stored = StoredFile.objects.get()
        version = stored.versions.get()
        self.client.post(reverse("storage:restore_version", args=[version.pk]))
        stored.refresh_from_db()
        version.refresh_from_db()
        self.assertEqual(self.read(stored.file), b"v1")
        self.assertEqual(self.read(version.file), b"v2")

    def test_download_version(self):
        self.upload(("report.txt", b"v1"))
        self.upload(("report.txt", b"v2"))
        version = FileVersion.objects.get()
        response = self.client.get(reverse("storage:download_version", args=[version.pk]))
        self.assertEqual(b"".join(response.streaming_content), b"v1")
        self.assertIn("report.txt", response["Content-Disposition"])

    def test_delete_version_removes_physical_file(self):
        self.upload(("report.txt", b"v1"))
        self.upload(("report.txt", b"v2"))
        version = FileVersion.objects.get()
        name, storage = version.file.name, version.file.storage
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("storage:delete_version", args=[version.pk]))
        self.assertFalse(storage.exists(name))
        self.assertTrue(StoredFile.objects.get().file.storage.exists(StoredFile.objects.get().file.name))

    @override_settings(STORAGE_MAX_VERSIONS=2)
    def test_old_versions_pruned(self):
        for content in (b"v1", b"v2", b"v3", b"v4"):
            self.upload(("report.txt", content))
        stored = StoredFile.objects.get()
        kept = [self.read(v.file) for v in stored.versions.order_by("-created_time")]
        self.assertEqual(kept, [b"v3", b"v2"])

    def test_purging_file_removes_versions(self):
        self.upload(("report.txt", b"v1"))
        self.upload(("report.txt", b"v2"))
        stored = StoredFile.objects.get()
        version = stored.versions.get()
        self.client.post(reverse("storage:delete_file", args=[stored.pk]))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("storage:purge_file", args=[stored.pk]))
        self.assertFalse(FileVersion.objects.exists())
        self.assertFalse(version.file.storage.exists(version.file.name))

    def test_version_shared_with_duplicate_is_kept(self):
        # 舊版本的內容和另一個檔案相同，刪除版本時不能刪掉共用的實體檔案
        self.upload(("report.txt", b"shared"))
        self.upload(("copy.txt", b"shared"))
        self.upload(("report.txt", b"newer"))
        version = FileVersion.objects.get()
        copy = StoredFile.objects.get(original_name="copy.txt")
        self.assertEqual(version.file.name, copy.file.name)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("storage:delete_version", args=[version.pk]))
        self.assertEqual(self.read(copy.file), b"shared")

    def test_other_user_cannot_access_versions(self):
        self.upload(("report.txt", b"v1"))
        self.upload(("report.txt", b"v2"))
        version = FileVersion.objects.get()
        stored = version.stored_file
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(reverse("storage:file_versions", args=[stored.pk])).status_code, 404)
        for name in ("download_version", "restore_version", "delete_version"):
            url = reverse(f"storage:{name}", args=[version.pk])
            self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(FileVersion.objects.exists())

    def test_list_shows_version_count(self):
        self.upload(("report.txt", b"v1"))
        self.upload(("report.txt", b"v2"))
        response = self.client.get(reverse("storage:browse"), {"view": "list"})
        self.assertContains(response, "版本（1）")
