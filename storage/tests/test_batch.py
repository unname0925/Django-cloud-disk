import io
import zipfile

from django.urls import reverse

from ..models import Folder, StoredFile
from .base import StorageTestCase


class BatchTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)
        self.docs = Folder.objects.create(owner=self.alice, name="docs")
        self.inner = self.upload_as(self.alice, ("inner.txt", b"I"), folder=self.docs)
        self.a = self.upload_as(self.alice, ("a.txt", b"A"))
        self.b = self.upload_as(self.alice, ("b.txt", b"B"))
        self.target = Folder.objects.create(owner=self.alice, name="target")

    def batch(self, action, files=(), folders=(), **extra):
        data = {"action": action, "file": [f.pk for f in files],
                "folder": [f.pk for f in folders], **extra}
        return self.client.post(reverse("storage:batch"), data)

    def test_move_files_and_folders(self):
        self.batch("move", files=[self.a, self.b], folders=[self.docs], target=self.target.pk)
        for item in (self.a, self.b, self.docs):
            item.refresh_from_db()
        self.assertEqual(self.a.folder, self.target)
        self.assertEqual(self.b.folder, self.target)
        self.assertEqual(self.docs.parent, self.target)

    def test_move_to_root(self):
        self.batch("move", files=[self.inner], target="")
        self.inner.refresh_from_db()
        self.assertIsNone(self.inner.folder)

    def test_cannot_move_folder_into_itself(self):
        sub = Folder.objects.create(owner=self.alice, parent=self.docs, name="sub")
        response = self.batch("move", folders=[self.docs], target=sub.pk)
        self.docs.refresh_from_db()
        self.assertIsNone(self.docs.parent)
        messages = [str(m) for m in response.wsgi_request._messages]
        self.assertTrue(any("自己或子資料夾" in m for m in messages))

    def test_move_renames_on_conflict(self):
        Folder.objects.create(owner=self.alice, parent=self.target, name="docs")
        self.batch("move", folders=[self.docs], target=self.target.pk)
        self.docs.refresh_from_db()
        self.assertEqual((self.docs.parent, self.docs.name), (self.target, "docs (2)"))

    def test_trash_selected(self):
        self.batch("trash", files=[self.a], folders=[self.docs])
        self.assertEqual(
            set(StoredFile.objects.active().values_list("original_name", flat=True)), {"b.txt"}
        )

    def test_folder_and_its_file_trashed_as_one_batch(self):
        # 在搜尋結果裡同時勾選資料夾與裡面的檔案，還原資料夾時檔案也要一起回來
        self.batch("trash", files=[self.inner], folders=[self.docs])
        self.client.post(reverse("storage:restore_folder", args=[self.docs.pk]))
        self.inner.refresh_from_db()
        self.assertIsNone(self.inner.deleted_time)

    def test_zip_selection(self):
        response = self.batch("zip", files=[self.a], folders=[self.docs])
        zf = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        self.assertEqual(set(zf.namelist()), {"a.txt", "docs/", "docs/inner.txt"})

    def test_zip_same_named_folders(self):
        other = Folder.objects.create(owner=self.alice, parent=self.target, name="docs")
        self.upload_as(self.alice, ("x.txt", b"X"), folder=other)
        response = self.batch("zip", folders=[self.docs, other])
        names = set(zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))).namelist())
        self.assertIn("docs/inner.txt", names)
        self.assertIn("docs (2)/x.txt", names)

    def test_nothing_selected(self):
        response = self.batch("trash")
        self.assertRedirects(response, reverse("storage:browse"))
        self.assertEqual(StoredFile.objects.trashed().count(), 0)

    def test_other_users_items_ignored(self):
        bobs = self.upload_as(self.bob, ("bob.txt", b"b"))
        bobs_folder = Folder.objects.create(owner=self.bob, name="bob")
        self.client.force_login(self.alice)
        self.batch("trash", files=[bobs], folders=[bobs_folder])
        bobs.refresh_from_db()
        bobs_folder.refresh_from_db()
        self.assertIsNone(bobs.deleted_time)
        self.assertIsNone(bobs_folder.deleted_time)
        # 也不能移到別人的資料夾
        response = self.batch("move", files=[self.a], target=bobs_folder.pk)
        self.assertEqual(response.status_code, 404)

    def test_redirects_back_to_safe_next(self):
        url = reverse("storage:browse_folder", args=[self.docs.pk])
        response = self.batch("trash", files=[self.inner], next=url)
        self.assertRedirects(response, url, fetch_redirect_response=False)
        response = self.batch("trash", files=[self.a], next="https://evil.example.com/")
        self.assertRedirects(response, reverse("storage:browse"))

    def test_list_view_has_checkboxes_and_targets(self):
        response = self.client.get(reverse("storage:browse"), {"view": "list"})
        self.assertContains(response, 'name="file"')
        self.assertContains(response, "data-batch-form")
        self.assertIn((self.target.pk, "target"), response.context["move_targets"])
