from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from ..models import Folder, StoredFile
from .base import StorageTestCase


class TrashTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)

    def trash_file(self, stored):
        self.client.post(reverse("storage:delete_file", args=[stored.pk]))
        stored.refresh_from_db()

    def trash_folder(self, folder):
        self.client.post(reverse("storage:delete_folder", args=[folder.pk]))
        folder.refresh_from_db()

    def test_trash_lists_only_top_level_items(self):
        docs = Folder.objects.create(owner=self.alice, name="docs")
        self.upload(("inner.txt", b"1"), folder=docs)
        loose = self.upload_as(self.alice, ("loose.txt", b"2"))
        self.trash_folder(docs)
        self.trash_file(loose)

        response = self.client.get(reverse("storage:trash"))
        self.assertEqual([f for f, _ in response.context["folders"]], [docs])
        self.assertEqual([f for f, _ in response.context["files"]], [loose])
        self.assertNotContains(response, "inner.txt")

    def test_restore_file(self):
        stored = self.upload_as(self.alice)
        self.trash_file(stored)
        self.client.post(reverse("storage:restore_file", args=[stored.pk]))
        stored.refresh_from_db()
        self.assertIsNone(stored.deleted_time)
        self.assertContains(self.client.get(reverse("storage:browse")), "hello.txt")

    def test_restore_folder_restores_same_batch_only(self):
        docs = Folder.objects.create(owner=self.alice, name="docs")
        earlier = self.upload_as(self.alice, ("earlier.txt", b"1"), folder=docs)
        later = self.upload_as(self.alice, ("later.txt", b"2"), folder=docs)
        self.trash_file(earlier)
        self.trash_folder(docs)

        self.client.post(reverse("storage:restore_folder", args=[docs.pk]))
        docs.refresh_from_db()
        later.refresh_from_db()
        earlier.refresh_from_db()
        self.assertIsNone(docs.deleted_time)
        self.assertIsNone(later.deleted_time)
        # 先前個別刪除的檔案仍留在回收筒，而且現在變成最上層項目
        self.assertIsNotNone(earlier.deleted_time)
        files = self.client.get(reverse("storage:trash")).context["files"]
        self.assertEqual([f for f, _ in files], [earlier])

    def test_restore_folder_with_name_conflict(self):
        docs = Folder.objects.create(owner=self.alice, name="docs")
        self.trash_folder(docs)
        Folder.objects.create(owner=self.alice, name="docs")
        self.client.post(reverse("storage:restore_folder", args=[docs.pk]))
        docs.refresh_from_db()
        self.assertEqual(docs.name, "docs (2)")

    def test_purge_file_removes_from_disk(self):
        stored = self.upload_as(self.alice)
        self.trash_file(stored)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("storage:purge_file", args=[stored.pk]))
        self.assertFalse(StoredFile.objects.exists())
        self.assertFalse(stored.file.storage.exists(stored.file.name))

    def test_cannot_purge_active_file(self):
        stored = self.upload_as(self.alice)
        response = self.client.post(reverse("storage:purge_file", args=[stored.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(StoredFile.objects.exists())

    def test_purge_folder_removes_contents_from_disk(self):
        docs = Folder.objects.create(owner=self.alice, name="docs")
        sub = Folder.objects.create(owner=self.alice, parent=docs, name="sub")
        stored = self.upload_as(self.alice, ("deep.txt", b"1"), folder=sub)
        self.trash_folder(docs)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("storage:purge_folder", args=[docs.pk]))
        self.assertFalse(Folder.objects.exists())
        self.assertFalse(stored.file.storage.exists(stored.file.name))

    def test_empty_trash_keeps_active_items(self):
        keep = self.upload_as(self.alice, ("keep.txt", b"1"))
        drop = self.upload_as(self.alice, ("drop.txt", b"2"))
        self.trash_file(drop)
        self.client.post(reverse("storage:empty_trash"))
        self.assertEqual(list(StoredFile.objects.all()), [keep])

    def test_other_user_cannot_touch_trash(self):
        stored = self.upload_as(self.alice)
        self.trash_file(stored)
        self.client.force_login(self.bob)
        for name in ("restore_file", "purge_file"):
            url = reverse(f"storage:{name}", args=[stored.pk])
            self.assertEqual(self.client.post(url).status_code, 404)
        self.client.post(reverse("storage:empty_trash"))
        self.assertTrue(StoredFile.objects.filter(pk=stored.pk).exists())

    def test_trash_still_counts_toward_quota(self):
        stored = self.upload_as(self.alice)
        self.trash_file(stored)
        self.assertEqual(self.client.get(reverse("storage:browse")).context["used_bytes"], 11)

    @override_settings(STORAGE_TRASH_RETENTION_DAYS=30)
    def test_expired_items_purged(self):
        old = self.upload_as(self.alice, ("old.txt", b"1"))
        recent = self.upload_as(self.alice, ("recent.txt", b"2"))
        self.trash_file(old)
        self.trash_file(recent)
        StoredFile.objects.filter(pk=old.pk).update(
            deleted_time=timezone.now() - timedelta(days=31)
        )

        with self.captureOnCommitCallbacks(execute=True):
            call_command("cleanup_storage", stdout=StringIO())

        self.assertEqual(list(StoredFile.objects.all()), [recent])
        self.assertFalse(old.file.storage.exists(old.file.name))

    @override_settings(STORAGE_TRASH_RETENTION_DAYS=30)
    def test_opening_trash_purges_expired_items(self):
        old = self.upload_as(self.alice)
        self.trash_file(old)
        StoredFile.objects.filter(pk=old.pk).update(
            deleted_time=timezone.now() - timedelta(days=31)
        )
        self.client.get(reverse("storage:trash"))
        self.assertFalse(StoredFile.objects.exists())
