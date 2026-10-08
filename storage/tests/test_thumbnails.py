import io

from django.urls import reverse
from PIL import Image

from .base import StorageTestCase


def make_png(size=(800, 400), mode="RGBA"):
    buffer = io.BytesIO()
    Image.new(mode, size, (255, 0, 0, 128) if mode == "RGBA" else "red").save(buffer, "PNG")
    return buffer.getvalue()


class ThumbnailTests(StorageTestCase):
    def test_thumbnail_generated_and_cached(self):
        stored = self.upload_as(self.alice, ("big.png", make_png()))
        url = reverse("storage:thumbnail", args=[stored.pk])

        response = self.client.get(url)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        image = Image.open(io.BytesIO(b"".join(response.streaming_content)))
        self.assertEqual(image.size, (320, 160))
        self.assertTrue(stored.file.storage.exists(stored.thumbnail_name))

        # 第二次直接使用快取
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_non_image_returns_404(self):
        stored = self.upload_as(self.alice, ("notes.txt", b"hello"))
        response = self.client.get(reverse("storage:thumbnail", args=[stored.pk]))
        self.assertEqual(response.status_code, 404)

    def test_corrupt_image_returns_404(self):
        stored = self.upload_as(self.alice, ("broken.jpg", b"not really a jpeg"))
        response = self.client.get(reverse("storage:thumbnail", args=[stored.pk]))
        self.assertEqual(response.status_code, 404)

    def test_other_user_cannot_view(self):
        stored = self.upload_as(self.alice, ("big.png", make_png()))
        self.client.force_login(self.bob)
        response = self.client.get(reverse("storage:thumbnail", args=[stored.pk]))
        self.assertEqual(response.status_code, 404)

    def test_thumbnail_deleted_with_file(self):
        stored = self.upload_as(self.alice, ("big.png", make_png()))
        self.client.get(reverse("storage:thumbnail", args=[stored.pk]))
        self.client.post(reverse("storage:delete_file", args=[stored.pk]))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("storage:purge_file", args=[stored.pk]))
        self.assertFalse(stored.file.storage.exists(stored.thumbnail_name))

    def test_gallery_view_uses_thumbnails_and_is_remembered(self):
        stored = self.upload_as(self.alice, ("big.png", make_png()))
        response = self.client.get(reverse("storage:browse"), {"view": "grid"})
        self.assertContains(response, reverse("storage:thumbnail", args=[stored.pk]))
        self.assertContains(response, "data-lightbox")
        # 下次進入時沿用相簿模式
        self.assertEqual(self.client.get(reverse("storage:browse")).context["view_mode"], "grid")
