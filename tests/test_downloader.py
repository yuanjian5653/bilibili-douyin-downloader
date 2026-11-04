"""下载器测试：使用本地 HTTP 服务，不访问外网。"""

from __future__ import annotations

import queue
import unittest
from pathlib import Path

from app.downloader import (
    DownloadError,
    create_session,
    download_file,
    ffmpeg_exe,
    make_temp_path,
)
from app.events import bus
from tests.helpers import AppTestCase, http_server

HEADERS = {"User-Agent": "unittest"}


class DownloadTests(AppTestCase):
    def test_success_with_progress(self):
        with http_server() as base:
            channel = bus.subscribe("bili")
            target = self.tmp_path / "video.mp4"
            result = download_file(f"{base}/payload", target, "视频流", HEADERS, "bili")

        self.assertEqual(result, target)
        self.assertEqual(target.stat().st_size, 256 * 1024 + 17)
        self.assertFalse((self.tmp_path / "video.mp4.part").exists())

        messages = []
        while True:
            try:
                messages.append(channel.get_nowait())
            except queue.Empty:
                break
        progresses = [item for item in messages if item.get("type") == "progress"]
        self.assertTrue(progresses, "应当推送进度事件")
        self.assertEqual(progresses[-1]["value"], 100.0)
        self.assertEqual(progresses[-1]["total"], 256 * 1024 + 17)
        self.assertTrue(any(item.get("type") == "log" for item in messages))

    def test_404_raises_and_cleans_up(self):
        with http_server() as base:
            target = self.tmp_path / "missing.mp4"
            with self.assertRaises(DownloadError):
                download_file(f"{base}/nope", target, "视频流", HEADERS, "bili")
        self.assertFalse(target.exists())
        self.assertFalse((self.tmp_path / "missing.mp4.part").exists())

    def test_uses_fallback_url(self):
        with http_server() as base:
            target = self.tmp_path / "fallback.mp4"
            download_file(
                f"{base}/nope", target, "视频流", HEADERS, "bili",
                fallback_urls=[f"{base}/payload"],
            )
        self.assertEqual(target.stat().st_size, 256 * 1024 + 17)

    def test_detects_truncated_body(self):
        with http_server() as base:
            target = self.tmp_path / "truncated.mp4"
            with self.assertRaises(DownloadError):
                download_file(f"{base}/partial", target, "视频流", HEADERS, "bili")
        self.assertFalse(target.exists())
        self.assertFalse((self.tmp_path / "truncated.mp4.part").exists())

    def test_overwrites_existing_file(self):
        with http_server() as base:
            target = self.tmp_path / "existing.mp4"
            target.write_bytes(b"old-content")
            download_file(f"{base}/payload", target, "视频流", HEADERS, "bili")
        self.assertEqual(target.stat().st_size, 256 * 1024 + 17)


class HelperTests(AppTestCase):
    def test_make_temp_path(self):
        first = make_temp_path(self.tmp_path, ".mp4")
        second = make_temp_path(self.tmp_path, ".mp4")
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, Path(self.tmp_path))
        self.assertEqual(first.suffix, ".mp4")

    def test_create_session_with_retries(self):
        session = create_session(headers={"X-Test": "1"}, retries=2)
        try:
            self.assertEqual(session.headers["X-Test"], "1")
            self.assertIn("https://", session.adapters)
        finally:
            session.close()

    def test_ffmpeg_exe_available(self):
        self.assertTrue(Path(ffmpeg_exe()).exists())


if __name__ == "__main__":
    unittest.main()
