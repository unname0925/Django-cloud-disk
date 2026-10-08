from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from ..models import Folder, StoredFile, UserProfile
from ..services import dedupe
from .base import StorageTestCase


class DedupeTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)

    def test_identical_upload_shares_storage(self):
        folder = Folder.objects.create(owner=self.alice, name="copy")
        first = self.upload_as(self.alice, ("a.txt", b"same content"))
        response = self.client.post(reverse("storage:upload"), {
            "files": [SimpleUploadedFile("b.txt", b"same content")], "folder": folder.pk,
        }, follow=True)
        self.assertContains(response, "共用儲存空間")

        second = StoredFile.objects.get(original_name="b.txt")
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.file.name, second.file.name)
        self.assertEqual(second.folder, folder)
        # 容量只算一次
        self.assertEqual(UserProfile.for_user(self.alice).used_bytes, len(b"same content"))

    def test_same_content_in_one_batch(self):
        self.upload(("a.txt", b"x"), ("b.txt", b"x"))
        names = set(StoredFile.objects.values_list("file", flat=True))
        self.assertEqual(len(names), 1)

    def test_different_users_do_not_share(self):
        mine = self.upload_as(self.alice, ("a.txt", b"same"))
        theirs = self.upload_as(self.bob, ("a.txt", b"same"))
        self.assertNotEqual(mine.file.name, theirs.file.name)

    def test_shared_physical_file_kept_until_last_reference(self):
        first = self.upload_as(self.alice, ("a.txt", b"shared"))
        second = self.upload_as(self.alice, ("b.txt", b"shared"))
        storage, name = first.file.storage, first.file.name

        with self.captureOnCommitCallbacks(execute=True):
            first.delete()
        self.assertTrue(storage.exists(name))
        with second.file.open("rb") as fh:
            self.assertEqual(fh.read(), b"shared")

        with self.captureOnCommitCallbacks(execute=True):
            second.delete()
        self.assertFalse(storage.exists(name))

    @override_settings(STORAGE_CHUNK_SIZE=8)
    def test_chunked_upload_dedupes(self):
        first = self.upload_as(self.alice, ("a.bin", b"0123456789"))
        session = self.client.post(reverse("storage:start_upload"),
                                   {"name": "b.bin", "size": 10}).json()["id"]
        url = reverse("storage:upload_session", args=[session])
        self.client.post(url, {"offset": 0, "chunk": SimpleUploadedFile("c", b"01234567")})
        data = self.client.post(url, {"offset": 8, "chunk": SimpleUploadedFile("c", b"89")}).json()
        second = StoredFile.objects.get(pk=data["file_id"])
        self.assertEqual(second.file.name, first.file.name)
        self.assertEqual(second.sha256, first.sha256)

    def test_backfill_hashes_and_merges_old_files(self):
        old_a = self.upload_as(self.alice, ("old-a.txt", b"legacy"))
        old_b = self.upload_as(self.alice, ("old-b.txt", b"legacy"))
        # 模擬功能上線前就存在、各自有實體檔案且沒有雜湊的舊檔案
        storage = old_b.file.storage
        copy_name = storage.save("users/legacy-copy.txt", old_b.file)
        StoredFile.objects.filter(pk=old_b.pk).update(file=copy_name, sha256="")
        StoredFile.objects.filter(pk=old_a.pk).update(sha256="")

        with self.captureOnCommitCallbacks(execute=True):
            processed, merged, _ = dedupe.backfill(self.alice)

        self.assertEqual((processed, merged), (2, 1))
        old_a.refresh_from_db()
        old_b.refresh_from_db()
        self.assertEqual(old_a.file.name, old_b.file.name)
        self.assertFalse(storage.exists(copy_name))

    def test_duplicates_page_groups_active_files(self):
        self.upload(("a.txt", b"dup"), ("b.txt", b"dup"), ("c.txt", b"unique"))
        response = self.client.get(reverse("storage:duplicates"))
        groups = response.context["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual({f.original_name for f in groups[0]["files"]}, {"a.txt", "b.txt"})

        # 刪到回收筒後就不算重複
        b = StoredFile.objects.get(original_name="b.txt")
        self.client.post(reverse("storage:delete_file", args=[b.pk]))
        self.assertEqual(self.client.get(reverse("storage:duplicates")).context["groups"], [])
