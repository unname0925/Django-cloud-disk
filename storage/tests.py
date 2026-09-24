import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import StoredFile, UserProfile

TEMP_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class StorageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.alice = User.objects.create_user("alice", password="S3cure-pass-alice")
        self.bob = User.objects.create_user("bob", password="S3cure-pass-bob")

    def upload(self, name="hello.txt", content=b"hello world"):
        return self.client.post(
            reverse("upload"),
            {"file": SimpleUploadedFile(name, content)},
        )

    def test_profile_created_on_register(self):
        self.assertTrue(UserProfile.objects.filter(user=self.alice).exists())

    def test_weak_password_rejected(self):
        response = self.client.post(reverse("register"), {
            "username": "carol",
            "password1": "123",
            "password2": "123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="carol").exists())

    def test_upload_stores_file_in_user_folder(self):
        self.client.force_login(self.alice)
        response = self.upload()
        self.assertRedirects(response, reverse("dashboard"))

        stored = StoredFile.objects.get(owner=self.alice)
        self.assertEqual(stored.original_name, "hello.txt")
        self.assertEqual(stored.file_size, 11)
        self.assertIn(str(self.alice.profile.folder_uuid), stored.file.name)

    def test_upload_without_profile(self):
        UserProfile.objects.filter(user=self.alice).delete()
        self.alice.refresh_from_db()
        self.client.force_login(self.alice)
        self.upload()
        self.assertEqual(StoredFile.objects.filter(owner=self.alice).count(), 1)

    def test_dashboard_shows_size_and_time(self):
        self.client.force_login(self.alice)
        self.upload()
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "hello.txt")
        self.assertContains(response, "11\xa0位元組")
        self.assertContains(response, str(StoredFile.objects.get(owner=self.alice).uploaded_time.year))

    def test_dashboard_only_lists_own_files(self):
        self.client.force_login(self.alice)
        self.upload("alice.txt")
        self.client.force_login(self.bob)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "alice.txt")

    def test_download_own_file(self):
        self.client.force_login(self.alice)
        self.upload()
        stored = StoredFile.objects.get(owner=self.alice)
        response = self.client.get(reverse("download", args=[stored.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"hello world")

    def test_cannot_access_other_users_file(self):
        self.client.force_login(self.alice)
        self.upload()
        stored = StoredFile.objects.get(owner=self.alice)

        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("download", args=[stored.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse("delete", args=[stored.id])).status_code, 404)
        self.assertTrue(StoredFile.objects.filter(id=stored.id).exists())

    def test_download_missing_file_returns_404(self):
        self.client.force_login(self.alice)
        self.upload()
        stored = StoredFile.objects.get(owner=self.alice)
        stored.file.storage.delete(stored.file.name)
        response = self.client.get(reverse("download", args=[stored.id]))
        self.assertEqual(response.status_code, 404)

    def test_delete_removes_file(self):
        self.client.force_login(self.alice)
        self.upload()
        stored = StoredFile.objects.get(owner=self.alice)
        name = stored.file.name
        response = self.client.post(reverse("delete", args=[stored.id]))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(StoredFile.objects.filter(id=stored.id).exists())
        self.assertFalse(stored.file.storage.exists(name))

    def test_login_required(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
