from django.urls import reverse

from ..models import ShareLink
from .base import StorageTestCase

CONTENT = bytes(range(256)) * 4  # 1024 bytes


class RangeTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.stored = self.upload_as(self.alice, ("clip.mp4", CONTENT))
        self.url = reverse("storage:preview_file", args=[self.stored.pk])

    def get(self, url=None, **headers):
        response = self.client.get(url or self.url, headers=headers)
        body = b"".join(response.streaming_content) if response.streaming else response.content
        return response, body

    def test_full_response_advertises_ranges(self):
        response, body = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertEqual(body, CONTENT)

    def test_partial_content(self):
        response, body = self.get(Range="bytes=100-199")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 100-199/1024")
        self.assertEqual(response["Content-Length"], "100")
        self.assertEqual(response["Content-Type"], "video/mp4")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertEqual(body, CONTENT[100:200])

    def test_open_ended_and_suffix(self):
        _, body = self.get(Range="bytes=1000-")
        self.assertEqual(body, CONTENT[1000:])
        response, body = self.get(Range="bytes=-24")
        self.assertEqual(response["Content-Range"], "bytes 1000-1023/1024")
        self.assertEqual(body, CONTENT[-24:])

    def test_end_beyond_size_is_clamped(self):
        response, body = self.get(Range="bytes=1020-5000")
        self.assertEqual(response["Content-Range"], "bytes 1020-1023/1024")
        self.assertEqual(body, CONTENT[1020:])

    def test_unsatisfiable(self):
        response, _ = self.get(Range="bytes=2000-")
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response["Content-Range"], "bytes */1024")

    def test_invalid_or_multi_range_returns_full(self):
        for header in ("bytes=abc", "bytes=0-1,5-6", "items=0-1", "bytes=50-10"):
            with self.subTest(header=header):
                response, body = self.get(Range=header)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(body, CONTENT)

    def test_if_range_returns_full(self):
        response, body = self.get(Range="bytes=0-9", **{"If-Range": "abc"})
        self.assertEqual(response.status_code, 200)

    def test_download_supports_resume(self):
        url = reverse("storage:download_file", args=[self.stored.pk])
        response, body = self.get(url, Range="bytes=512-")
        self.assertEqual(response.status_code, 206)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(body, CONTENT[512:])

    def test_shared_download_counts_only_initial_requests(self):
        self.client.post(reverse("storage:manage_shares", args=[self.stored.pk]),
                         {"expires_in_days": "", "max_downloads": "1"})
        link = ShareLink.objects.get()
        self.client.logout()
        url = reverse("storage:shared_download", args=[link.token])

        self.assertEqual(self.get(url, Range="bytes=0-99")[0].status_code, 206)
        # 續傳或拖曳進度條不會再扣次數
        response, body = self.get(url, Range="bytes=100-")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(body, CONTENT[100:])
        link.refresh_from_db()
        self.assertEqual(link.download_count, 1)
        # 次數用完後，新的完整下載會被拒絕
        self.assertEqual(self.get(url)[0].status_code, 410)

    def test_cannot_bypass_limit_with_ranges(self):
        self.client.post(reverse("storage:manage_shares", args=[self.stored.pk]),
                         {"expires_in_days": "", "max_downloads": "1"})
        link = ShareLink.objects.get()
        self.client.logout()
        url = reverse("storage:shared_download", args=[link.token])
        self.get(url)  # 第一位訪客用掉唯一的一次

        # 另一位訪客（新的 session）用 Range 拼湊檔案，仍然會被擋下
        self.client.cookies.clear()
        self.assertEqual(self.get(url, Range="bytes=1-")[0].status_code, 410)
        self.assertEqual(self.get(url, Range="bytes=-1")[0].status_code, 410)
