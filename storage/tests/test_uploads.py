import os
from datetime import timedelta
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from ..models import Folder, StoredFile, UploadSession, UserProfile
from .base import StorageTestCase

CONTENT = b"0123456789abcdefghij"  # 20 bytes


@override_settings(STORAGE_CHUNK_SIZE=8)
class ChunkedUploadTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.alice)

    def start(self, name="big.bin", size=len(CONTENT), folder=None):
        data = {"name": name, "size": size}
        if folder is not None:
            data["folder"] = folder.pk
        return self.client.post(reverse("storage:start_upload"), data)

    def send(self, session_id, offset, data):
        return self.client.post(
            reverse("storage:upload_session", args=[session_id]),
            {"offset": offset, "chunk": SimpleUploadedFile("chunk", data)},
        )

    def upload_all(self, session_id, content=CONTENT, chunk=8):
        response = None
        for offset in range(0, len(content), chunk):
            response = self.send(session_id, offset, content[offset:offset + chunk])
        return response

    def test_full_upload(self):
        folder = Folder.objects.create(owner=self.alice, name="docs")
        started = self.start(folder=folder)
        self.assertEqual(started.status_code, 201)
        session_id = started.json()["id"]

        response = self.upload_all(session_id)
        data = response.json()
        self.assertTrue(data["done"])

        stored = StoredFile.objects.get(pk=data["file_id"])
        self.assertEqual(stored.folder, folder)
        self.assertEqual(stored.file_size, 20)
        with stored.file.open("rb") as fh:
            self.assertEqual(fh.read(), CONTENT)
        self.assertFalse(UploadSession.objects.exists())

    def test_resume_after_interruption(self):
        session_id = self.start().json()["id"]
        self.send(session_id, 0, CONTENT[:8])

        # 重新整理頁面後，前端先查詢目前進度
        status = self.client.get(reverse("storage:upload_session", args=[session_id])).json()
        self.assertEqual(status["received_bytes"], 8)

        self.send(session_id, 8, CONTENT[8:16])
        done = self.send(session_id, 16, CONTENT[16:]).json()
        self.assertTrue(done["done"])
        with StoredFile.objects.get().file.open("rb") as fh:
            self.assertEqual(fh.read(), CONTENT)

    def test_wrong_offset_returns_current_progress(self):
        session_id = self.start().json()["id"]
        self.send(session_id, 0, CONTENT[:8])
        # 前端以為第一段沒送到，重送一次
        response = self.send(session_id, 0, CONTENT[:8])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["received_bytes"], 8)

    def test_retry_after_partial_write_overwrites_tail(self):
        session_id = self.start().json()["id"]
        self.send(session_id, 0, CONTENT[:8])
        # 模擬寫入檔案後、更新資料庫前伺服器中斷：暫存檔比紀錄的進度多出垃圾資料
        session = UploadSession.objects.get()
        with open(session.part_path, "ab") as fh:
            fh.write(b"garbage")
        self.send(session_id, 8, CONTENT[8:16])
        self.send(session_id, 16, CONTENT[16:])
        with StoredFile.objects.get().file.open("rb") as fh:
            self.assertEqual(fh.read(), CONTENT)

    def test_rejects_oversized_chunk(self):
        session_id = self.start().json()["id"]
        response = self.send(session_id, 0, CONTENT[:9])
        self.assertEqual(response.status_code, 400)

    def test_rejects_data_beyond_declared_size(self):
        session_id = self.start(size=10).json()["id"]
        self.send(session_id, 0, CONTENT[:8])
        response = self.send(session_id, 8, CONTENT[8:16])
        self.assertEqual(response.status_code, 400)

    def test_empty_file_completes_immediately(self):
        data = self.start(name="empty.txt", size=0).json()
        self.assertTrue(data["done"])
        self.assertEqual(StoredFile.objects.get().file_size, 0)

    @override_settings(STORAGE_MAX_UPLOAD_SIZE=10)
    def test_size_limit(self):
        response = self.start(size=11)
        self.assertEqual(response.status_code, 413)
        self.assertFalse(UploadSession.objects.exists())

    def test_quota_checked_at_start_and_finish(self):
        profile = UserProfile.for_user(self.alice)
        profile.quota_bytes = 25
        profile.save()

        self.assertEqual(self.start(size=26).status_code, 413)

        # 兩個上傳同時開始，各自都在容量內，但第二個完成時已經超過
        first = self.start().json()["id"]
        second = self.start().json()["id"]
        self.upload_all(first)
        response = self.upload_all(second)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(StoredFile.objects.count(), 1)
        self.assertFalse(UploadSession.objects.exists())

    def test_filename_is_sanitized(self):
        data = self.start(name="../../etc/pass:wd", size=0).json()
        stored = StoredFile.objects.get(pk=data["file_id"])
        self.assertEqual(stored.original_name, "pass_wd")
        self.assertIn(str(self.alice.profile.folder_uuid), stored.file.name)

    def test_cannot_upload_into_other_users_folder(self):
        bobs = Folder.objects.create(owner=self.bob, name="bob")
        self.assertEqual(self.start(folder=bobs).status_code, 400)

    def test_other_user_cannot_use_session(self):
        session_id = self.start().json()["id"]
        self.client.force_login(self.bob)
        self.assertEqual(self.send(session_id, 0, CONTENT[:8]).status_code, 404)
        url = reverse("storage:upload_session", args=[session_id])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_cancel(self):
        session_id = self.start().json()["id"]
        self.send(session_id, 0, CONTENT[:8])
        part = UploadSession.objects.get().part_path
        self.client.post(reverse("storage:cancel_upload", args=[session_id]))
        self.assertFalse(UploadSession.objects.exists())
        self.assertFalse(part.exists())

    def test_folder_trashed_during_upload_falls_back_to_root(self):
        folder = Folder.objects.create(owner=self.alice, name="docs")
        session_id = self.start(folder=folder).json()["id"]
        self.client.post(reverse("storage:delete_folder", args=[folder.pk]))
        file_id = self.upload_all(session_id).json()["file_id"]
        self.assertIsNone(StoredFile.objects.get(pk=file_id).folder)

    @override_settings(STORAGE_UPLOAD_SESSION_HOURS=24)
    def test_cleanup_removes_stale_sessions(self):
        stale_id = self.start().json()["id"]
        self.send(stale_id, 0, CONTENT[:8])
        fresh_id = self.start().json()["id"]
        stale = UploadSession.objects.get(pk=stale_id)
        UploadSession.objects.filter(pk=stale_id).update(
            updated_time=timezone.now() - timedelta(hours=25)
        )
        # 沒有 session 的舊暫存檔也會被清除
        orphan = stale.part_path.with_name("orphan.part")
        orphan.write_bytes(b"x")
        old = (timezone.now() - timedelta(hours=25)).timestamp()
        os.utime(orphan, (old, old))

        call_command("cleanup_storage", stdout=StringIO())

        self.assertEqual(list(UploadSession.objects.values_list("pk", flat=True)),
                         [UploadSession.objects.get(pk=fresh_id).pk])
        self.assertFalse(stale.part_path.exists())
        self.assertFalse(orphan.exists())

    def test_upload_page_has_drop_zone(self):
        response = self.client.get(reverse("storage:upload"))
        self.assertContains(response, "data-upload-zone")
        self.assertContains(response, "uploader.js")
