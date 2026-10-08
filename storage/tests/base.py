import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import StoredFile


class StorageTestCase(TestCase):
    """每個測試類別都使用獨立的暫存目錄存放上傳檔案。"""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp()
        cls._media_override = override_settings(
            MEDIA_ROOT=cls._media_root,
            # 測試不需要安全的密碼雜湊，換成快速版本以縮短執行時間
            PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
        )
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="S3cure-pass-alice")
        self.bob = User.objects.create_user("bob", password="S3cure-pass-bob")

    def upload(self, *files, folder=None):
        """上傳檔案；files 為 (檔名, 內容) 組合，預設上傳一個 hello.txt。"""
        files = files or (("hello.txt", b"hello world"),)
        data = {"files": [SimpleUploadedFile(name, content) for name, content in files]}
        if folder is not None:
            data["folder"] = folder.pk
        return self.client.post(reverse("storage:upload"), data)

    def upload_as(self, user, *files, folder=None):
        self.client.force_login(user)
        self.upload(*files, folder=folder)
        return StoredFile.objects.filter(owner=user).latest("pk")
