"""Flask 路由集成测试（网络与浏览器全部打桩）。"""

from __future__ import annotations

import unittest
from pathlib import Path

from app import bilibili, douyin, routes
from app.config import DOWNLOAD_DIR, VERSION
from app.events import bus
from app.state import STATE
from tests.helpers import AppTestCase, http_server, wait_for

BV = "BV1xx411c7mD"


class RouteTests(AppTestCase):
    @classmethod
    def setUpClass(cls):
        from app import create_app

        cls.app = create_app()
        cls.app.config.update(TESTING=True)

    def setUp(self):
        super().setUp()
        self.client = self.app.test_client()

    # ---------- 基础页面 ----------
    def test_index_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="bili-url"', html)
        self.assertIn('id="douyin-text"', html)
        self.assertIn(f"v{VERSION}", html)
        self.assertIn(str(DOWNLOAD_DIR), html)

    def test_health(self):
        payload = self.client.get("/api/health").get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], VERSION)
        self.assertEqual(payload["busy"], {"bili": False, "douyin": False})

    def test_unknown_api_returns_json_404(self):
        response = self.client.get("/api/not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.is_json)
        self.assertFalse(response.get_json()["ok"])

    def test_unknown_platform_stream(self):
        response = self.client.get("/api/stream/kuaishou")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()["ok"])

    def test_stream_headers_and_hello(self):
        response = self.client.get("/api/stream/bili", buffered=False)
        self.assertEqual(response.mimetype, "text/event-stream")
        self.assertTrue(response.headers["Cache-Control"].startswith("no-cache"))
        iterator = iter(response.response)
        first = next(iterator)
        second = next(iterator)
        if isinstance(first, bytes):
            first = first.decode()
        if isinstance(second, bytes):
            second = second.decode()
        self.assertIn("retry:", first)
        self.assertIn('"type": "hello"', second)
        response.close()

    # ---------- B站登录 ----------
    def test_bili_status_not_logged_in(self):
        self.assertFalse(self.client.get("/api/bili/status").get_json()["logged_in"])

    def test_bili_cookie_empty(self):
        response = self.client.post("/api/bili/cookie", json={"cookie": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_bili_cookie_invalid(self):
        self.patch(bilibili, "check_login", lambda session: False)
        response = self.client.post("/api/bili/cookie", json={"cookie": "SESSDATA=bad"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("无效", response.get_json()["msg"])

    def test_bili_cookie_valid_and_saved(self):
        self.patch(bilibili, "check_login", lambda session: True)
        response = self.client.post(
            "/api/bili/cookie", json={"cookie": "SESSDATA=ok; bili_jct=x"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertTrue(self.client.get("/api/bili/status").get_json()["logged_in"])
        self.assertTrue((self.tmp_path / "cookies.pkl").exists())

    def test_bili_clear(self):
        STATE.apply_cookies(bilibili.cookies_from_string("SESSDATA=ok"))
        response = self.client.post("/api/bili/clear")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.get("/api/bili/status").get_json()["logged_in"])

    # ---------- B站解析 / 下载 ----------
    def _patch_bili(self, title="测试视频"):
        self.patch(
            bilibili, "fetch_video_info",
            lambda session, url: bilibili.VideoInfo(
                bvid=BV, aid=1, cid=222, title=title, page=1, page_count=1
            ),
        )
        self.patch(
            bilibili, "fetch_streams",
            lambda session, bvid, cid: bilibili.Streams(
                videos=[
                    bilibili.StreamOption(64, "720P", "AVC", "https://example/720", 900),
                    bilibili.StreamOption(80, "1080P", "HEVC", "https://example/1080", 2000),
                ],
                audio=None,
                is_dash=False,
            ),
        )

    def test_bili_parse_requires_url(self):
        self.assertEqual(
            self.client.post("/api/bili/parse", json={}).status_code, 400
        )

    def test_bili_parse_success(self):
        self.patch(bilibili, "check_login", lambda session: False)
        self._patch_bili()
        channel = bus.subscribe("bili")
        response = self.client.post(
            "/api/bili/parse", json={"url": f"https://www.bilibili.com/video/{BV}"}
        )
        self.assertEqual(response.status_code, 200)
        event = wait_for(channel, "bili_parsed")
        self.assertEqual(event["title"], "测试视频")
        self.assertEqual(event["qualities"], ["720P · AVC", "1080P · HEVC"])
        self.assertEqual(event["default_index"], 1)
        self.assertFalse(event["has_audio"])
        self.assertEqual(STATE.bili_video["cid"], 222)

    def test_bili_parse_busy_returns_409(self):
        STATE.begin_task("bili")
        try:
            response = self.client.post("/api/bili/parse", json={"url": "x"})
            self.assertEqual(response.status_code, 409)
            self.assertFalse(response.get_json()["ok"])
        finally:
            STATE.end_task("bili")

    def test_bili_download_requires_parse(self):
        response = self.client.post("/api/bili/download", json={"mode": "full"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("解析", response.get_json()["msg"])

    def test_bili_download_invalid_mode(self):
        STATE.bili_video = {"title": "t", "options": [], "audio": None, "is_dash": False}
        response = self.client.post("/api/bili/download", json={"mode": "weird"})
        self.assertEqual(response.status_code, 400)

    def test_bili_download_video_only(self):
        with http_server() as base:
            STATE.bili_video = {
                "bvid": BV,
                "cid": 222,
                "title": "测试/视频:1?",
                "page": 1,
                "options": [{
                    "qn": 64, "desc": "720P", "codecs": "AVC",
                    "url": f"{base}/payload", "backup_urls": [], "bandwidth": 900,
                }],
                "audio": None,
                "is_dash": False,
            }
            channel = bus.subscribe("bili")
            response = self.client.post("/api/bili/download", json={
                "mode": "video_only",
                "quality_index": 0,
                "save_dir": str(self.tmp_path / "out"),
            })
            self.assertEqual(response.status_code, 200)
            event = wait_for(channel, "done", timeout=20)

        path = Path(event["path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "测试_视频_1__无声.mp4")
        self.assertEqual(path.stat().st_size, 256 * 1024 + 17)

    def test_bili_download_out_of_range_quality_falls_back(self):
        with http_server() as base:
            STATE.bili_video = {
                "bvid": BV, "cid": 1, "title": "视频", "page": 1,
                "options": [{
                    "qn": 16, "desc": "360P", "codecs": "AVC",
                    "url": f"{base}/payload", "backup_urls": [], "bandwidth": 1,
                }],
                "audio": None, "is_dash": False,
            }
            channel = bus.subscribe("bili")
            self.client.post("/api/bili/download", json={
                "mode": "video_only", "quality_index": 99, "save_dir": str(self.tmp_path),
            })
            event = wait_for(channel, "done", timeout=20)
        self.assertTrue(Path(event["path"]).exists())

    # ---------- 抖音 ----------
    def test_douyin_parse_requires_text(self):
        self.assertEqual(
            self.client.post("/api/douyin/parse", json={"text": "  "}).status_code, 400
        )

    def test_douyin_parse_success(self):
        self.patch(
            douyin, "fetch_video_info",
            lambda text, platform="douyin": douyin.DouyinInfo(
                title="抖音作品", video_url="https://v/1.mp4",
                audio_url="https://a/1.mp3", aweme_id="1",
            ),
        )
        channel = bus.subscribe("douyin")
        response = self.client.post(
            "/api/douyin/parse", json={"text": "看看 https://v.douyin.com/abc/ 复制"}
        )
        self.assertEqual(response.status_code, 200)
        event = wait_for(channel, "douyin_parsed")
        self.assertEqual(event["title"], "抖音作品")
        self.assertEqual(STATE.douyin_video["video_url"], "https://v/1.mp4")

    def test_douyin_parse_error_event(self):
        def boom(text, platform="douyin"):
            raise douyin.DouyinError("解析失败示例")

        self.patch(douyin, "fetch_video_info", boom)
        channel = bus.subscribe("douyin")
        self.client.post("/api/douyin/parse", json={"text": "https://v.douyin.com/abc/"})
        event = wait_for(channel, "douyin_parsed")
        self.assertEqual(event["error"], "解析失败示例")

    def test_douyin_download_requires_parse(self):
        response = self.client.post("/api/douyin/download", json={"mode": "full"})
        self.assertEqual(response.status_code, 400)

    def test_douyin_download_video(self):
        with http_server() as base:
            STATE.douyin_video = {
                "title": "抖音视频",
                "video_url": f"{base}/payload",
                "audio_url": None,
                "aweme_id": "1",
            }
            channel = bus.subscribe("douyin")
            self.client.post(
                "/api/douyin/download",
                json={"mode": "full", "save_dir": str(self.tmp_path)},
            )
            event = wait_for(channel, "done", timeout=20)
        path = Path(event["path"])
        self.assertEqual(path.suffix, ".mp4")
        self.assertEqual(path.stat().st_size, 256 * 1024 + 17)

    # ---------- 本地交互 ----------
    def test_browse_disabled(self):
        self.patch(routes, "ENABLE_BROWSE_DIALOG", False)
        response = self.client.post("/api/browse")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_reveal_rejects_unknown_path(self):
        response = self.client.post(
            "/api/reveal", json={"path": str(self.tmp_path / "x.mp4")}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("只能打开", response.get_json()["msg"])

    def test_reveal_rejects_missing_path(self):
        self.assertEqual(self.client.post("/api/reveal", json={}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
