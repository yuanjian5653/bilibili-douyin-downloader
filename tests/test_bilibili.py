"""B站解析相关单元测试（全部使用伪造响应，不访问网络）。"""

from __future__ import annotations

import json
import os
import sys
import types
import unittest
from unittest import mock

from app import bilibili
from app.bilibili import (
    BiliError,
    StreamOption,
    codec_label,
    cookies_from_string,
    extract_json_object,
    extract_video_id,
    fetch_streams,
    fetch_video_info,
    is_short_link,
    parse_initial_state,
    quality_desc,
)
from tests.helpers import AppTestCase

BV = "BV1xx411c7mD"


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return FakeResponse(self.payload)


DASH_PAYLOAD = {
    "code": 0,
    "data": {
        "support_formats": [
            {"quality": 80, "new_description": "1080P 高清"},
            {"quality": 64, "new_description": "720P 高清"},
        ],
        "dash": {
            "video": [
                {"id": 80, "baseUrl": "https://v/1080-avc", "codecs": "avc1.640028",
                 "bandwidth": 2000, "backupUrl": ["https://b/1080"]},
                {"id": 80, "baseUrl": "https://v/1080-hevc", "codecs": "hev1.1.6",
                 "bandwidth": 1500},
                {"id": 64, "baseUrl": "https://v/720", "codecs": "avc1.64001f",
                 "bandwidth": 900},
                {"id": 80, "baseUrl": "https://v/1080-dup", "codecs": "avc1.640028",
                 "bandwidth": 1000},
            ],
            "audio": [
                {"id": 30216, "baseUrl": "https://a/64", "codecs": "mp4a.40.2",
                 "bandwidth": 64000},
                {"id": 30280, "baseUrl": "https://a/192", "codecs": "mp4a.40.2",
                 "bandwidth": 192000, "backupUrl": ["https://a/192b"]},
            ],
        },
    },
}


class LinkParsingTests(unittest.TestCase):
    def test_extract_video_id_bv(self):
        self.assertEqual(
            extract_video_id(f"https://www.bilibili.com/video/{BV}")["bvid"], BV
        )
        self.assertEqual(
            extract_video_id(f"https://www.bilibili.com/video/{BV}?p=3")["page"], 3
        )
        self.assertEqual(
            extract_video_id(
                f"https://www.bilibili.com/video/{BV}?spm_id_from=x&p=12"
            )["page"],
            12,
        )

    def test_extract_video_id_av(self):
        parsed = extract_video_id("https://www.bilibili.com/video/av170001")
        self.assertEqual(parsed["aid"], 170001)
        self.assertIsNone(parsed["bvid"])

    def test_extract_video_id_invalid(self):
        for raw in ("", "https://www.bilibili.com/"):
            with self.subTest(raw=raw), self.assertRaises(BiliError):
                extract_video_id(raw)
        with self.assertRaises(BiliError):
            extract_video_id("https://www.bilibili.com/bangumi/play/ep123456")

    def test_is_short_link(self):
        self.assertTrue(is_short_link("https://b23.tv/abcd"))
        self.assertTrue(is_short_link("https://bili2233.cn/abcd"))
        self.assertFalse(is_short_link(f"https://www.bilibili.com/video/{BV}"))


class JsonExtractionTests(unittest.TestCase):
    def test_handles_braces_in_strings(self):
        text = 'xx {"a": "value }; with brace", "b": {"c": [1, 2]}} tail'
        raw = extract_json_object(text, text.index("{"))
        self.assertIsNotNone(raw)
        data = json.loads(raw)
        self.assertEqual(data["a"], "value }; with brace")
        self.assertEqual(data["b"]["c"], [1, 2])

    def test_invalid_start(self):
        self.assertIsNone(extract_json_object("no json here", 0))
        self.assertIsNone(extract_json_object("{unclosed", 0))

    def test_parse_initial_state(self):
        html = (
            '<html><script>window.__INITIAL_STATE__={"videoData":{"bvid":"'
            + BV
            + '","title":"标题 }} ;"}};(function(){var x=1;})();</script></html>'
        )
        data = parse_initial_state(html)
        self.assertIsNotNone(data)
        self.assertEqual(data["videoData"]["bvid"], BV)

    def test_parse_initial_state_missing(self):
        self.assertIsNone(parse_initial_state("<html></html>"))


class QualityTests(unittest.TestCase):
    def test_codec_label(self):
        self.assertEqual(codec_label("avc1.640032"), "AVC")
        self.assertEqual(codec_label("hev1.1.6.4"), "HEVC")
        self.assertEqual(codec_label("av01.0.08M.08"), "AV1")
        self.assertEqual(codec_label("mp4a.40.2"), "AAC")
        self.assertEqual(codec_label(""), "未知")

    def test_quality_desc(self):
        formats = [{"quality": 80, "new_description": "1080P 高清"}]
        self.assertEqual(quality_desc(80, formats), "1080P 高清")
        self.assertEqual(quality_desc(64, formats), "720P")
        self.assertEqual(quality_desc(9999, formats), "未知(9999)")

    def test_dedupe_keeps_codecs_and_highest_bandwidth(self):
        options = [
            StreamOption(80, "1080P", "AVC", "url-a", 1000),
            StreamOption(80, "1080P", "AVC", "url-b", 2000),
            StreamOption(80, "1080P", "HEVC", "url-c", 1500),
            StreamOption(64, "720P", "AVC", "url-d", 900),
        ]
        result = bilibili._dedupe_videos(options)
        self.assertEqual(
            [(item.qn, item.codecs, item.bandwidth) for item in result],
            [(64, "AVC", 900), (80, "AVC", 2000), (80, "HEVC", 1500)],
        )


class StreamApiTests(unittest.TestCase):
    def test_fetch_streams_dash(self):
        session = FakeSession(DASH_PAYLOAD)
        streams = fetch_streams(session, BV, 12345)
        self.assertTrue(streams.is_dash)
        self.assertEqual(
            [(item.qn, item.codecs) for item in streams.videos],
            [(64, "AVC"), (80, "AVC"), (80, "HEVC")],
        )
        best = streams.videos[1]
        self.assertEqual(best.url, "https://v/1080-avc")
        self.assertEqual(best.desc, "1080P 高清")
        self.assertEqual(best.backup_urls, ["https://b/1080"])
        self.assertIsNotNone(streams.audio)
        self.assertEqual(streams.audio.url, "https://a/192")
        self.assertEqual(streams.audio.backup_urls, ["https://a/192b"])
        params = session.calls[0]["params"]
        self.assertEqual(params["bvid"], BV)
        self.assertEqual(params["cid"], 12345)
        self.assertGreaterEqual(params["fnval"], 16)

    def test_fetch_streams_durl_fallback(self):
        payload = {
            "code": 0,
            "data": {
                "quality": 64,
                "support_formats": [{"quality": 64, "new_description": "720P"}],
                "durl": [{"url": "https://x/1.mp4", "backup_url": ["https://x/2.mp4"]}],
            },
        }
        streams = fetch_streams(FakeSession(payload), BV, 1)
        self.assertFalse(streams.is_dash)
        self.assertIsNone(streams.audio)
        self.assertEqual(streams.videos[0].url, "https://x/1.mp4")
        self.assertEqual(streams.videos[0].backup_urls, ["https://x/2.mp4"])

    def test_fetch_streams_multi_part_durl_raises(self):
        payload = {"code": 0, "data": {"durl": [{"url": "a"}, {"url": "b"}]}}
        with self.assertRaises(BiliError):
            fetch_streams(FakeSession(payload), BV, 1)

    def test_fetch_streams_error_code(self):
        with self.assertRaises(BiliError):
            fetch_streams(FakeSession({"code": -403, "message": "访问权限不足"}), BV, 1)

    def test_fetch_streams_no_dash_no_durl(self):
        with self.assertRaises(BiliError):
            fetch_streams(FakeSession({"code": 0, "data": {}}), BV, 1)


class VideoInfoTests(AppTestCase):
    def test_page_and_title(self):
        payload = {
            "code": 0,
            "data": {
                "bvid": BV,
                "aid": 123,
                "cid": 111,
                "title": "总标题",
                "pages": [
                    {"cid": 111, "part": "第一集"},
                    {"cid": 222, "part": "第二集"},
                ],
            },
        }
        self.patch(bilibili, "_get_json", lambda *a, **k: payload)
        info = fetch_video_info(
            FakeSession(payload), f"https://www.bilibili.com/video/{BV}?p=2"
        )
        self.assertEqual(info.cid, 222)
        self.assertEqual(info.page, 2)
        self.assertEqual(info.page_count, 2)
        self.assertIn("第二集", info.title)

    def test_page_out_of_range(self):
        payload = {"code": 0, "data": {"title": "t", "pages": [{"cid": 1}]}}
        self.patch(bilibili, "_get_json", lambda *a, **k: payload)
        with self.assertRaises(BiliError):
            fetch_video_info(
                FakeSession(payload), f"https://www.bilibili.com/video/{BV}?p=9"
            )

    def test_api_error(self):
        payload = {"code": -404, "message": "啥都木有"}
        self.patch(bilibili, "_get_json", lambda *a, **k: payload)
        with self.assertRaises(BiliError):
            fetch_video_info(FakeSession(payload), f"https://www.bilibili.com/video/{BV}")


class CookieTests(unittest.TestCase):
    def test_cookies_from_string(self):
        jar = cookies_from_string("Cookie: SESSDATA=abc%2C123; bili_jct=xyz; 无效项")
        self.assertEqual(jar.get("SESSDATA"), "abc%2C123")
        self.assertEqual(jar.get("bili_jct"), "xyz")
        self.assertEqual(len(jar), 2)

    def test_quoted_value(self):
        jar = cookies_from_string('SESSDATA="quoted-value"')
        self.assertEqual(jar.get("SESSDATA"), "quoted-value")

    def test_empty(self):
        self.assertEqual(len(cookies_from_string("")), 0)
        self.assertEqual(len(cookies_from_string(";;;")), 0)


class BrowserDirTests(AppTestCase):
    """自动登录用的浏览器目录与启动参数（不真正启动浏览器）。"""

    def test_prepare_browser_dirs_creates_writable_dirs(self):
        profile, temp = bilibili.prepare_browser_dirs(self.tmp_path)
        self.assertTrue(profile.is_dir())
        self.assertTrue(temp.is_dir())
        self.assertTrue(str(profile).startswith(str(self.tmp_path)))
        (temp / "probe.txt").write_text("ok", encoding="utf-8")
        (profile / "probe.txt").write_text("ok", encoding="utf-8")

    def test_prepare_browser_dirs_uses_unique_profile(self):
        first, _ = bilibili.prepare_browser_dirs(self.tmp_path)
        second, _ = bilibili.prepare_browser_dirs(self.tmp_path)
        self.assertNotEqual(first, second)

    def test_prepare_browser_dirs_raises_when_unwritable(self):
        blocker = self.tmp_path / "blocked"
        blocker.write_text("not a dir", encoding="utf-8")
        with self.assertRaises(bilibili.BiliError):
            bilibili.prepare_browser_dirs(blocker, fallback_to_temp=False)

    def test_service_env_redirects_temp(self):
        env = bilibili._service_env(self.tmp_path)
        self.assertEqual(env["TEMP"], str(self.tmp_path))
        self.assertEqual(env["TMP"], str(self.tmp_path))
        self.assertEqual(env["TMPDIR"], str(self.tmp_path))

    def test_service_env_sets_selenium_cache(self):
        temp = self.tmp_path / "temp"
        temp.mkdir()
        env = bilibili._service_env(temp)
        self.assertEqual(env["SE_CACHE_PATH"], str(self.tmp_path / "selenium"))
        self.assertTrue((self.tmp_path / "selenium").is_dir())

    def test_apply_selenium_env_syncs_process_env(self):
        """Selenium Manager 由 Python 进程直接调用，缓存路径必须写进 os.environ。"""
        cache = str(self.tmp_path / "cache")
        env = {"SE_CACHE_PATH": cache, "SE_AVOID_STATS": "true"}
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SE_CACHE_PATH", None)
            bilibili._apply_selenium_env(env)
            self.assertEqual(os.environ["SE_CACHE_PATH"], cache)
            self.assertEqual(os.environ["SE_AVOID_STATS"], "true")
            bilibili._apply_selenium_env({})
            self.assertEqual(os.environ["SE_CACHE_PATH"], cache)

    def test_browser_args_include_own_profile(self):
        profile = self.tmp_path / "profile"
        temp = self.tmp_path / "temp"
        args = bilibili._browser_args(profile, temp)
        self.assertIn(f"--user-data-dir={profile}", args)
        self.assertIn(f"--disk-cache-dir={temp / 'cache'}", args)
        self.assertNotIn("--headless=new", args)

    def test_browser_args_headless(self):
        args = bilibili._browser_args(self.tmp_path / "p", self.tmp_path / "t", headless=True)
        self.assertIn("--headless=new", args)


class DriverVersionTests(AppTestCase):
    """浏览器与驱动版本适配逻辑（纯函数，不启动浏览器）。"""

    def test_parse_driver_version(self):
        text = "Microsoft Edge WebDriver 156.0.4295.0 (c9bec3e8b0b7d3a552e2e009f7b72bccea065614)"
        self.assertEqual(bilibili._parse_driver_version(text), "156.0.4295.0")
        self.assertIsNone(bilibili._parse_driver_version("no version here"))
        self.assertIsNone(bilibili._parse_driver_version(""))

    def test_version_major(self):
        self.assertEqual(bilibili._version_major("156.0.4295.0"), 156)
        self.assertIsNone(bilibili._version_major(None))
        self.assertIsNone(bilibili._version_major("abc"))
        self.assertIsNone(bilibili._version_major(""))

    def test_same_major(self):
        self.assertIs(bilibili._same_major("156.0.4295.0", "156.0.4314.58"), True)
        self.assertIs(bilibili._same_major("155.0.1.1", "156.0.4314.58"), False)
        self.assertIsNone(bilibili._same_major(None, "156.0.1.1"))
        self.assertIsNone(bilibili._same_major("156.0.1.1", None))

    def test_detect_versions_never_crash(self):
        for value in (bilibili.detect_edge_version(), bilibili.detect_chrome_version()):
            self.assertTrue(value is None or isinstance(value, str))

    def test_driver_version_missing_file(self):
        self.assertIsNone(bilibili._driver_version(self.tmp_path / "nope.exe"))


class SeleniumStartupTests(AppTestCase):
    """selenium 启动流程：必须走显式子模块导入（伪造模块，不启动浏览器）。"""

    class FakeOptions:
        def __init__(self):
            self.args = []
            self.experimental = None
            self.timeout = None

        def add_argument(self, arg, *args):
            self.args.append(arg)

        def add_experimental_option(self, name, value):
            self.experimental = (name, value)

    class FakeService:
        def __init__(self, executable_path=None, env=None):
            self.executable_path = executable_path
            self.env = env

    class FakeDriver:
        def __init__(self, options=None, service=None):
            self.options = options
            self.service = service
            self.url = None
            self.quit_called = False

        def set_page_load_timeout(self, value):
            self.timeout = value

        def get(self, url):
            self.url = url

        def quit(self):
            self.quit_called = True

    def _install_selenium(self, drivers: dict[str, type]) -> None:
        """把伪造的 selenium 模块塞进 ``sys.modules``；drivers 是 浏览器 -> WebDriver。"""
        modules = {
            "selenium": types.ModuleType("selenium"),
            "selenium.webdriver": types.ModuleType("selenium.webdriver"),
        }
        for browser, driver in drivers.items():
            prefix = f"selenium.webdriver.{browser}"
            modules[prefix] = types.ModuleType(prefix)
            webdriver_module = types.ModuleType(f"{prefix}.webdriver")
            webdriver_module.WebDriver = driver
            options_module = types.ModuleType(f"{prefix}.options")
            options_module.Options = self.FakeOptions
            service_module = types.ModuleType(f"{prefix}.service")
            service_module.Service = self.FakeService
            modules[f"{prefix}.webdriver"] = webdriver_module
            modules[f"{prefix}.options"] = options_module
            modules[f"{prefix}.service"] = service_module
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _prepare(self):
        self.patch(bilibili, "detect_edge_version", lambda: "156.0.4314.58")
        self.patch(bilibili, "detect_chrome_version", lambda: None)
        # 项目根目录里的旧 msedgedriver.exe 不参与测试
        self.patch(bilibili, "resource_path", lambda name: str(self.tmp_path / name))
        return self.tmp_path / "profile", self.tmp_path / "temp"

    def test_import_driver_classes_returns_fakes(self):
        self._install_selenium({"edge": self.FakeDriver})
        webdriver_cls, options_cls, service_cls = bilibili._import_driver_classes("edge")
        self.assertIs(webdriver_cls, self.FakeDriver)
        self.assertIs(options_cls, self.FakeOptions)
        self.assertIs(service_cls, self.FakeService)

    def test_start_browser_uses_full_module_path(self):
        self._install_selenium({"edge": self.FakeDriver, "chrome": self.FakeDriver})
        profile, temp = self._prepare()

        driver = bilibili._start_browser(profile, temp)
        self.assertIsInstance(driver, self.FakeDriver)
        self.assertEqual(driver.url, "about:blank")
        self.assertTrue(any(arg.startswith("--user-data-dir=") for arg in driver.options.args))

    def test_falls_back_to_chrome_when_edge_fails(self):
        class BrokenDriver(self.FakeDriver):
            def __init__(self, options=None, service=None):
                raise RuntimeError("session not created: edge boom")

        self._install_selenium({"edge": BrokenDriver, "chrome": self.FakeDriver})
        profile, temp = self._prepare()

        driver = bilibili._start_browser(profile, temp)
        self.assertIsInstance(driver, self.FakeDriver)
        self.assertNotIsInstance(driver, BrokenDriver)

    def test_reports_every_failure_reason(self):
        calls: list[list[str]] = []

        class BrokenDriver(self.FakeDriver):
            def __init__(self, options=None, service=None):
                calls.append(options.args)
                raise RuntimeError("session not created: tab crashed")

        self._install_selenium({"edge": BrokenDriver, "chrome": BrokenDriver})
        profile, temp = self._prepare()

        with self.assertRaises(BiliError) as ctx:
            bilibili._start_browser(profile, temp)
        message = str(ctx.exception)
        self.assertIn("Edge", message)
        self.assertIn("Chrome", message)
        self.assertIn("tab crashed", message)
        self.assertIn("--no-sandbox", message)
        self.assertEqual(len(calls), 4)  # Edge / Edge+no-sandbox / Chrome / Chrome+no-sandbox

    def test_missing_module_reports_actionable_error(self):
        error = ImportError("No module named 'selenium.webdriver.edge.webdriver'")
        with mock.patch("importlib.import_module", side_effect=error):
            with self.assertRaises(BiliError) as ctx:
                bilibili._import_driver_classes("edge")
        message = str(ctx.exception)
        self.assertIn("pip install", message)
        self.assertIn("手动粘贴 Cookie", message)

    def test_start_browser_reports_missing_modules(self):
        profile, temp = self._prepare()
        error = ImportError("No module named 'selenium.webdriver.edge.webdriver'")
        with mock.patch("importlib.import_module", side_effect=error):
            with self.assertRaises(BiliError) as ctx:
                bilibili._start_browser(profile, temp)
        self.assertIn("手动粘贴 Cookie", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
