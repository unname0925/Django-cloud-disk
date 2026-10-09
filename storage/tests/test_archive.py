import io
import zipfile

from django.urls import reverse

from ..models import Folder
from .base import StorageTestCase


class ZipDownloadTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)
        self.docs = Folder.objects.create(owner=self.alice, name="docs")
        self.sub = Folder.objects.create(owner=self.alice, parent=self.docs, name="sub")
        self.empty = Folder.objects.create(owner=self.alice, parent=self.docs, name="empty")
        self.upload(("a.txt", b"A"), folder=self.docs)
        # 同一個資料夾上傳同名檔案會變成新版本；重新命名則可能出現同名檔案
        self.upload(("other.txt", b"A2"), folder=self.docs)
        other = self.docs.files.get(original_name="other.txt")
        self.client.post(reverse("storage:rename_file", args=[other.pk]), {"name": "a.txt"})
        self.upload(("photo.jpg", b"JPG"), folder=self.sub)
        self.upload(("root.txt", b"R"))

    def get_zip(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        return response, zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))

    def test_folder_zip_structure(self):
        response, zf = self.get_zip(reverse("storage:download_folder", args=[self.docs.pk]))
        self.assertIn("docs.zip", response["Content-Disposition"])
        names = set(zf.namelist())
        self.assertEqual(names, {"a.txt", "a (2).txt", "sub/", "sub/photo.jpg", "empty/"})
        self.assertEqual(zf.read("sub/photo.jpg"), b"JPG")
        self.assertEqual(zf.getinfo("sub/photo.jpg").compress_type, zipfile.ZIP_STORED)
        self.assertEqual(zf.getinfo("a.txt").compress_type, zipfile.ZIP_DEFLATED)

    def test_download_all(self):
        _, zf = self.get_zip(reverse("storage:download_all"))
        self.assertIn("root.txt", zf.namelist())
        self.assertIn("docs/sub/photo.jpg", zf.namelist())

    def test_trashed_items_excluded(self):
        self.client.post(reverse("storage:delete_folder", args=[self.sub.pk]))
        _, zf = self.get_zip(reverse("storage:download_folder", args=[self.docs.pk]))
        self.assertNotIn("sub/photo.jpg", zf.namelist())
        self.assertNotIn("sub/", zf.namelist())

    def test_other_users_files_excluded(self):
        self.upload_as(self.bob, ("bob.txt", b"B"))
        self.client.force_login(self.alice)
        _, zf = self.get_zip(reverse("storage:download_all"))
        self.assertNotIn("bob.txt", zf.namelist())
        self.client.force_login(self.bob)
        url = reverse("storage:download_folder", args=[self.docs.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
