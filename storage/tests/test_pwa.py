import json

from django.contrib.staticfiles import finders
from django.urls import reverse

from .base import StorageTestCase


class PwaTests(StorageTestCase):
    def test_manifest(self):
        response = self.client.get(reverse("storage:manifest"))
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = json.loads(response.content)
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["start_url"], reverse("storage:browse"))
        self.assertEqual(data["scope"], reverse("storage:browse"))
        # 安裝成 App 需要 192 與 512 兩種尺寸，另外提供 maskable 圖示
        sizes = {icon["sizes"] for icon in data["icons"]}
        self.assertEqual(sizes, {"192x192", "512x512"})
        self.assertTrue(any(icon.get("purpose") == "maskable" for icon in data["icons"]))
        for icon in data["icons"]:
            self.assertIsNotNone(finders.find(icon["src"].removeprefix("/static/")))

    def test_service_worker_served_under_prefix(self):
        response = self.client.get(reverse("storage:service_worker"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/javascript")
        self.assertIn("no-cache", response["Cache-Control"])
        body = b"".join(response.streaming_content).decode()
        # 只快取靜態檔案與離線頁面，不快取使用者的頁面或檔案
        self.assertIn('"/static/"', body)
        self.assertIn("offline/", body)

    def test_offline_page_has_no_user_data(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("storage:offline"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "alice")

    def test_pages_link_manifest_and_register_worker(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("storage:browse"))
        self.assertContains(response, f'rel="manifest" href="{reverse("storage:manifest")}"')
        self.assertContains(response, "storage/pwa.js")
        self.assertContains(response, 'name="theme-color"')


class MobileTests(StorageTestCase):
    def test_camera_upload_button(self):
        self.client.force_login(self.alice)
        for url in (reverse("storage:browse"), reverse("storage:upload")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, 'capture="environment"')
                self.assertContains(response, "拍照上傳")

    def test_list_cells_have_labels_for_card_layout(self):
        self.upload_as(self.alice)
        response = self.client.get(reverse("storage:browse"), {"view": "list"})
        self.assertContains(response, 'data-label="大小"')
        self.assertContains(response, 'data-label="上傳時間"')
