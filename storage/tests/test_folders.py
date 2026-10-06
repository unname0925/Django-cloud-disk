from django.urls import reverse

from ..models import Folder, StoredFile
from .base import StorageTestCase


class FolderTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)

    def test_create_folder_in_root_and_subfolder(self):
        self.client.post(reverse("storage:create_folder"), {"name": "docs"})
        docs = Folder.objects.get(owner=self.alice, name="docs")
        response = self.client.post(
            reverse("storage:create_subfolder", args=[docs.pk]), {"name": "2026"}
        )
        self.assertRedirects(response, reverse("storage:browse_folder", args=[docs.pk]))
        self.assertTrue(docs.children.filter(name="2026").exists())

    def test_duplicate_name_rejected(self):
        Folder.objects.create(owner=self.alice, name="docs")
        response = self.client.post(reverse("storage:create_folder"), {"name": "docs"})
        self.assertContains(response, "相同名稱")
        self.assertEqual(Folder.objects.filter(name="docs").count(), 1)

    def test_same_name_allowed_for_different_users(self):
        Folder.objects.create(owner=self.bob, name="docs")
        self.client.post(reverse("storage:create_folder"), {"name": "docs"})
        self.assertTrue(Folder.objects.filter(owner=self.alice, name="docs").exists())

    def test_browse_folder_shows_breadcrumbs_and_contents(self):
        docs = Folder.objects.create(owner=self.alice, name="docs")
        sub = Folder.objects.create(owner=self.alice, parent=docs, name="sub")
        self.upload(("inner.txt", b"1"), folder=sub)
        self.upload(("outer.txt", b"2"))

        response = self.client.get(reverse("storage:browse_folder", args=[sub.pk]))
        self.assertEqual(response.context["breadcrumbs"], [docs, sub])
        self.assertContains(response, "inner.txt")
        self.assertNotContains(response, "outer.txt")

    def test_other_users_folder_is_404(self):
        bobs = Folder.objects.create(owner=self.bob, name="bob")
        for name in ("browse_folder", "rename_folder", "delete_folder", "create_subfolder"):
            with self.subTest(view=name):
                url = reverse(f"storage:{name}", args=[bobs.pk])
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_rename_folder(self):
        docs = Folder.objects.create(owner=self.alice, name="docs")
        self.client.post(reverse("storage:rename_folder", args=[docs.pk]), {"name": "papers"})
        docs.refresh_from_db()
        self.assertEqual(docs.name, "papers")

    def test_delete_folder_removes_contents_from_disk(self):
        docs = Folder.objects.create(owner=self.alice, name="docs")
        sub = Folder.objects.create(owner=self.alice, parent=docs, name="sub")
        self.upload(("a.txt", b"1"), folder=docs)
        self.upload(("b.txt", b"2"), folder=sub)
        stored = list(StoredFile.objects.all())

        confirm = self.client.get(reverse("storage:delete_folder", args=[docs.pk]))
        self.assertEqual(confirm.context["file_count"], 2)
        self.assertEqual(confirm.context["subfolder_count"], 1)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("storage:delete_folder", args=[docs.pk]))

        self.assertFalse(Folder.objects.exists())
        self.assertFalse(StoredFile.objects.exists())
        for f in stored:
            self.assertFalse(f.file.storage.exists(f.file.name))
