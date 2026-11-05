"""抖音解析相关单元测试（不启动浏览器、不访问网络）。"""

from __future__ import annotations

import json
import unittest
import urllib.parse

from app import douyin
from app.douyin import (
    DouyinError,
    build_info,
    extract_share_url,
    find_aweme_from_html,
    parse_render_data,
    parse_router_data,
    pick_audio_url,
    pick_video_url,
    strip_watermark,
)
from tests.helpers import AppTestCase

AWEME = {
    "aweme_id": "7300000000000000001",
    "desc": "一个测试作品",
    "video": {
        "play_addr": {"url_list": ["https://aweme.snssdk.com/aweme/v1/playwm/?video_id=v1"]},
        "bit_rate": [
            {"bit_rate": 1000, "play_addr": {"url_list": ["https://low/playwm/"]}},
            {"bit_rate": 5000, "play_addr": {"url_list": ["https://high/playwm/"]}},
        ],
    },
    "music": {"play_url": {"url_list": ["https://music/1.mp3"]}},
}


class ShareUrlTests(unittest.TestCase):
    def test_extract_share_url(self):
        cases = [
            ("7.43 复制打开抖音 https://v.douyin.com/iRNBho6u/ 看看视频",
             "https://v.douyin.com/iRNBho6u/"),
            ("https://v.douyin.com/abcDEF12", "https://v.douyin.com/abcDEF12"),
            ("https://www.douyin.com/video/7300000000000000001",
             "https://www.douyin.com/video/7300000000000000001"),
            ("https://www.douyin.com/note/7300000000000000001?x=1",
             "https://www.douyin.com/note/7300000000000000001?x=1"),
            ("https://www.iesdouyin.com/share/video/7300000000000000001",
             "https://www.iesdouyin.com/share/video/7300000000000000001"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(extract_share_url(text), expected)

    def test_invalid(self):
        for text in ("", "  ", "没有链接的文本", "https://example.com/video/1"):
            with self.subTest(text=text), self.assertRaises(DouyinError):
                extract_share_url(text)


class WatermarkTests(unittest.TestCase):
    def test_path_and_param(self):
        url = ("https://aweme.snssdk.com/aweme/v1/playwm/?video_id=v0200"
               "&watermark=1&ratio=720p")
        cleaned = strip_watermark(url)
        self.assertNotIn("/playwm/", cleaned)
        self.assertNotIn("watermark=", cleaned)
        self.assertTrue(cleaned.endswith("ratio=720p"))
        self.assertNotIn("&&", cleaned)

    def test_empty(self):
        self.assertEqual(strip_watermark(""), "")


class EmbeddedDataTests(unittest.TestCase):
    @staticmethod
    def _router_html(aweme: dict) -> str:
        data = {"loaderData": {"video_(id)/page": {"videoInfoRes": {"item_list": [aweme]}}}}
        return (
            "<html><script>window._ROUTER_DATA = "
            f"{json.dumps(data, ensure_ascii=False)};</script></html>"
        )

    def test_parse_router_data_and_find_aweme(self):
        html = self._router_html(AWEME)
        self.assertIsNotNone(parse_router_data(html))
        aweme = find_aweme_from_html(html)
        self.assertIsNotNone(aweme)
        self.assertEqual(aweme["aweme_id"], AWEME["aweme_id"])
        self.assertEqual(aweme["desc"], AWEME["desc"])

    def test_parse_render_data_url_encoded(self):
        payload = {"aweme": {"aweme_id": "123", "desc": "render", "video": {}}}
        encoded = urllib.parse.quote(json.dumps(payload))
        html = f'<script id="RENDER_DATA" type="application/json">{encoded}</script>'
        self.assertIsNotNone(parse_render_data(html))
        aweme = find_aweme_from_html(html)
        self.assertIsNotNone(aweme)
        self.assertEqual(aweme["aweme_id"], "123")

    def test_missing(self):
        self.assertIsNone(find_aweme_from_html("<html></html>"))
        self.assertIsNone(parse_router_data("<html></html>"))
        self.assertIsNone(parse_render_data("<html></html>"))


class AwemeFieldTests(unittest.TestCase):
    def test_pick_video_url_prefers_highest_bitrate(self):
        self.assertEqual(pick_video_url(AWEME), "https://high/play/")

    def test_pick_video_url_falls_back_to_play_addr(self):
        aweme = {"video": {"play_addr": {"url_list": ["https://a/playwm/"]}}}
        self.assertEqual(pick_video_url(aweme), "https://a/play/")

    def test_pick_video_url_missing(self):
        self.assertIsNone(pick_video_url({}))
        self.assertIsNone(pick_video_url({"video": {"play_addr": {"url_list": []}}}))

    def test_pick_audio_url(self):
        self.assertEqual(pick_audio_url(AWEME), "https://music/1.mp3")
        self.assertIsNone(pick_audio_url({}))

    def test_build_info(self):
        info = build_info(AWEME)
        self.assertEqual(info.title, "一个测试作品")
        self.assertEqual(info.video_url, "https://high/play/")
        self.assertEqual(info.audio_url, "https://music/1.mp3")
        self.assertEqual(info.aweme_id, "7300000000000000001")

    def test_build_info_image_post_rejected(self):
        with self.assertRaises(DouyinError):
            build_info({"aweme_id": "1", "images": [{"url": "x"}], "video": {}})

    def test_build_info_without_video_rejected(self):
        with self.assertRaises(DouyinError):
            build_info({"aweme_id": "1", "desc": "t", "video": {}})

    def test_build_info_title_fallback(self):
        info = build_info({"aweme_id": "999", "desc": "   ", "video": AWEME["video"]})
        self.assertEqual(info.title, "douyin_999")


class FakeListen:
    def __init__(self, packet, error: Exception | None = None):
        self.packet = packet
        self.error = error
        self.started = None
        self.stopped = False
        self.start_count = 0

    def start(self, *args, **kwargs):
        self.start_count += 1
        if self.error is not None:
            raise self.error
        self.started = (args, kwargs)

    def wait(self, *args, **kwargs):
        return self.packet

    def stop(self):
        self.stopped = True


class FakeResponse:
    def __init__(self, body):
        self.body = body


class FakePacket:
    def __init__(self, body):
        self.response = FakeResponse(body)


class FakeStates:
    def __init__(self, alive: bool = True):
        self.is_alive = alive


class FakeBrowser:
    def __init__(self, tab_ids: tuple[str, ...] = ("tab-1",)):
        self.tab_ids = tab_ids


class FakePage:
    def __init__(self, packet=None, html="", alive=True, tab_id="tab-1",
                 tab_ids=("tab-1",), listen_error: Exception | None = None):
        self.listen = FakeListen(packet, error=listen_error)
        self.html = html
        self.visited = None
        self.quit_called = False
        self.states = FakeStates(alive)
        self.browser = FakeBrowser(tab_ids)
        self.tab_id = tab_id

    def get(self, url):
        self.visited = url

    def wait(self):
        return None

    def quit(self):
        self.quit_called = True


CLOSED_ERROR = RuntimeError("浏览器未开启或已关闭。\n版本: 4.1.1.4")


class BrowserFlowTests(AppTestCase):
    def test_uses_api_packet(self):
        page = FakePage(packet=FakePacket({"aweme_detail": AWEME}))
        self.patch(douyin, "_get_page", lambda: page)
        info = douyin.fetch_video_info("https://v.douyin.com/abc/", "douyin")
        self.assertEqual(info.title, "一个测试作品")
        self.assertEqual(page.visited, "https://v.douyin.com/abc/")
        self.assertTrue(page.listen.stopped)

    def test_falls_back_to_html(self):
        html = EmbeddedDataTests._router_html(AWEME)
        page = FakePage(packet=None, html=html)
        self.patch(douyin, "_get_page", lambda: page)
        info = douyin.fetch_video_info("https://v.douyin.com/abc/", "douyin")
        self.assertEqual(info.aweme_id, AWEME["aweme_id"])

    def test_no_data_raises(self):
        page = FakePage(packet=None, html="<html>no data</html>")
        self.patch(douyin, "_get_page", lambda: page)
        with self.assertRaises(DouyinError):
            douyin.fetch_video_info("https://v.douyin.com/abc/", "douyin")


class PageLifecycleTests(AppTestCase):
    """浏览器窗口被关掉之后，复用缓存页面必须先探活再重建。"""

    def test_alive_page_is_reused(self):
        page = FakePage()
        self.patch(douyin, "_page", page)
        self.patch(douyin, "_build_page", self._fail_build)
        self.assertIs(douyin._get_page(), page)

    @staticmethod
    def _fail_build():
        raise AssertionError("页面可用时不应该重建浏览器")

    def test_closed_browser_is_rebuilt(self):
        dead = FakePage(alive=False)
        fresh = FakePage()
        self.patch(douyin, "_page", dead)
        self.patch(douyin, "_build_page", lambda: fresh)

        self.assertIs(douyin._get_page(), fresh)
        self.assertTrue(dead.quit_called)
        self.assertIs(douyin._page, fresh)

    def test_closed_tab_is_detected(self):
        page = FakePage(tab_id="tab-1", tab_ids=("tab-2",))
        self.assertFalse(douyin._page_alive(page))

    def test_page_alive_requires_live_states(self):
        self.assertFalse(douyin._page_alive(None))
        self.assertFalse(douyin._page_alive(FakePage(alive=False)))
        self.assertTrue(douyin._page_alive(FakePage()))


class BrowserRecoveryTests(AppTestCase):
    """解析过程中浏览器失效时自动重启并重试一次。"""

    def test_retries_after_browser_closed(self):
        dead = FakePage(listen_error=CLOSED_ERROR)
        healthy = FakePage(packet=FakePacket({"aweme_detail": AWEME}))
        pages = [dead, healthy]
        self.patch(douyin, "_get_page", lambda: pages.pop(0))
        self.patch(douyin, "close_browser", lambda: None)

        info = douyin.fetch_video_info("https://v.douyin.com/abc/", "douyin")
        self.assertEqual(info.aweme_id, AWEME["aweme_id"])
        self.assertEqual(healthy.visited, "https://v.douyin.com/abc/")

    def test_reports_clear_error_after_second_failure(self):
        pages = [FakePage(listen_error=CLOSED_ERROR), FakePage(listen_error=CLOSED_ERROR)]
        self.patch(douyin, "_get_page", lambda: pages.pop(0))
        self.patch(douyin, "close_browser", lambda: None)

        with self.assertRaises(DouyinError) as ctx:
            douyin.fetch_video_info("https://v.douyin.com/abc/", "douyin")
        message = str(ctx.exception)
        self.assertIn("浏览器", message)
        self.assertIn("浏览器未开启或已关闭", message)

    def test_reports_browser_start_failure(self):
        def broken_page():
            raise RuntimeError("浏览器连接失败。\n地址: 127.0.0.1:1")

        self.patch(douyin, "_get_page", broken_page)
        with self.assertRaises(DouyinError) as ctx:
            douyin.fetch_video_info("https://v.douyin.com/abc/", "douyin")
        self.assertIn("浏览器启动失败", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
