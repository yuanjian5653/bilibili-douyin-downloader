"""抖音无水印解析。

抖音短链会跳转到分享页，页面既可能触发 ``aweme/detail`` 接口，也可能直接
在 HTML 里内嵌 ``window._ROUTER_DATA`` / ``RENDER_DATA``。这里同时支持两条
路径：先监听接口，超时后回退到页面数据解析。
"""

from __future__ import annotations

import atexit
import json
import re
import threading
import urllib.parse
from dataclasses import dataclass
from typing import Any

from .config import (
    DOUYIN_API_TIMEOUT,
    DOUYIN_BROWSER_PATH,
    DOUYIN_BROWSER_PORT,
    DOUYIN_HEADLESS,
)
from .events import log
from .utils import extract_first_url

DOUYIN_DETAIL_API = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

_DOUYIN_URL_RE = re.compile(
    r"https?://(?:"
    r"v\.douyin\.com/[A-Za-z0-9_\-]+/?"
    r"|(?:www\.|m\.)?(?:ies)?douyin\.com/[^\s<>\"'，。；：！？、（）【】]+"
    r")",
    re.IGNORECASE,
)


class DouyinError(RuntimeError):
    """抖音解析错误，消息可直接展示给用户。"""


@dataclass
class DouyinInfo:
    title: str
    video_url: str
    audio_url: str | None
    aweme_id: str = ""


# ===================== 文本 / 数据解析 =====================
def extract_share_url(text: str) -> str:
    """从「复制链接」得到的整段分享文案里提取链接。"""
    if not text or not text.strip():
        raise DouyinError("请粘贴抖音分享内容")
    match = _DOUYIN_URL_RE.search(text)
    if match:
        return match.group(0).rstrip(".,;:!?，。；：！？、")
    url = extract_first_url(text)
    if url and "douyin.com" in url:
        return url
    raise DouyinError("未找到有效的抖音链接，请粘贴包含 v.douyin.com 的分享文案")


def _find_aweme(node: Any, depth: int = 0) -> dict | None:
    """在任意嵌套结构里查找带有 aweme_id 的作品对象。"""
    if depth > 12:
        return None
    if isinstance(node, dict):
        if node.get("aweme_id") and ("video" in node or "images" in node or "desc" in node):
            return node
        for value in node.values():
            found = _find_aweme(value, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_aweme(item, depth + 1)
            if found:
                return found
    return None


def _extract_json_after(text: str, marker: str) -> dict | None:
    index = text.find(marker)
    if index < 0:
        return None
    brace = text.find("{", index)
    if brace < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for pos in range(brace, len(text)):
        char = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[brace:pos + 1])
                except ValueError:
                    return None
    return None


def parse_router_data(html: str) -> dict | None:
    """解析 ``window._ROUTER_DATA``。"""
    return _extract_json_after(html or "", "_ROUTER_DATA")


def parse_render_data(html: str) -> dict | None:
    """解析分享页里的 ``<script id="RENDER_DATA">``（内容为 URL 编码的 JSON）。"""
    if not html:
        return None
    match = re.search(
        r'<script[^>]+id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if not match:
        return None
    try:
        return json.loads(urllib.parse.unquote(match.group(1)))
    except ValueError:
        return None


def find_aweme_from_html(html: str) -> dict | None:
    for parser in (parse_router_data, parse_render_data):
        data = parser(html)
        aweme = _find_aweme(data) if data else None
        if aweme:
            return aweme
    return None


def strip_watermark(url: str) -> str:
    """把带水印的播放地址换成无水印地址。"""
    if not url:
        return url
    cleaned = url.replace("/playwm/", "/play/").replace("playwm", "play")
    cleaned = re.sub(r"([?&])watermark=\d+", r"\1", cleaned)
    cleaned = cleaned.replace("&&", "&").rstrip("?&")
    return cleaned


def _first_url(container: dict | None) -> str | None:
    if not isinstance(container, dict):
        return None
    for item in container.get("url_list") or []:
        if item:
            return item
    return None


def pick_video_url(aweme: dict) -> str | None:
    """按码率从高到低挑选视频地址。"""
    video = aweme.get("video") or {}
    play_addr = video.get("play_addr") or {}
    direct = _first_url(play_addr)
    rates = video.get("bit_rate") or []
    if rates:
        best = max(rates, key=lambda item: item.get("bit_rate") or 0)
        best_addr = _first_url(best.get("play_addr"))
        if best_addr:
            direct = best_addr
    if direct:
        return strip_watermark(direct)
    for key in ("download_addr", "play_addr_h264", "play_addr_265"):
        candidate = _first_url(video.get(key))
        if candidate:
            return strip_watermark(candidate)
    return None


def pick_audio_url(aweme: dict) -> str | None:
    music = aweme.get("music") or {}
    return _first_url(music.get("play_url")) or _first_url(music.get("play_url_h265"))


def build_info(aweme: dict) -> DouyinInfo:
    """从 aweme 作品数据里整理出标题与音视频地址。"""
    if aweme.get("images"):
        raise DouyinError("这是图文作品，暂不支持下载")
    video_url = pick_video_url(aweme)
    if not video_url:
        raise DouyinError("未找到可下载的视频地址（作品可能已删除或需要登录）")
    title = (aweme.get("desc") or "").strip() or f"douyin_{aweme.get('aweme_id', 'video')}"
    return DouyinInfo(
        title=title,
        video_url=video_url,
        audio_url=pick_audio_url(aweme),
        aweme_id=str(aweme.get("aweme_id") or ""),
    )


# ===================== 浏览器（DrissionPage） =====================
_page = None
_page_lock = threading.Lock()
_fetch_lock = threading.Lock()


def _build_page():
    """创建 ChromiumPage；DrissionPage 延迟导入，避免拖慢启动速度。"""
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise DouyinError("未安装 DrissionPage，请执行 pip install DrissionPage") from exc

    options = ChromiumOptions()
    if DOUYIN_BROWSER_PORT:
        options.set_local_port(DOUYIN_BROWSER_PORT)
    else:
        options.auto_port()  # 随机端口，避免与已运行的浏览器冲突
    if DOUYIN_HEADLESS:
        options.headless(True)
    if DOUYIN_BROWSER_PATH:
        options.set_browser_path(DOUYIN_BROWSER_PATH)
    options.set_argument("--disable-blink-features", "AutomationControlled")
    options.set_argument("--mute-audio")
    return ChromiumPage(options)


def _first_line(text: str, limit: int = 160) -> str:
    """DrissionPage 的错误信息常带换行和版本号，只取第一行用于界面展示。"""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[0][:limit] if lines else "未知错误"


def _page_alive(page) -> bool:
    """复用的浏览器页面是否还能用。

    用户手动关掉抖音的浏览器窗口后，DrissionPage 的页面对象仍然存在，但 CDP
    连接已经断开：这时 ``page.listen.start()`` 会抛「浏览器未开启或已关闭」。
    因此每次复用前都先探活，失效就重建。
    """
    if page is None:
        return False
    try:
        if not page.states.is_alive:
            return False
    except Exception:
        return False
    try:
        tab_ids = page.browser.tab_ids
    except Exception:
        return True  # 查不到标签页列表时交给后续流程判断，避免误重启
    if tab_ids and getattr(page, "tab_id", None) not in tab_ids:
        return False
    return True


def _dispose_page() -> None:
    """关闭并清空缓存的页面（调用方需持有 ``_page_lock``）。"""
    global _page
    if _page is None:
        return
    try:
        _page.quit()
    except Exception:
        pass
    _page = None


def _get_page():
    global _page
    with _page_lock:
        if _page is not None and not _page_alive(_page):
            log("douyin", "浏览器窗口已关闭，正在重新启动 ...", "warn")
            _dispose_page()
        if _page is None:
            log("douyin", "正在启动浏览器（首次较慢）...")
            _page = _build_page()
            try:
                if not DOUYIN_HEADLESS:
                    _page.set.window.max()
            except Exception:
                pass
        return _page


def close_browser() -> None:
    """关闭复用的浏览器实例。"""
    with _page_lock:
        _dispose_page()


atexit.register(close_browser)


def _packet_body(packet) -> dict | None:
    response = getattr(packet, "response", None)
    body = getattr(response, "body", None)
    if isinstance(body, dict):
        return body
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except ValueError:
            return None
    return None


def _aweme_from_packet(body: dict) -> dict | None:
    aweme = body.get("aweme_detail")
    if isinstance(aweme, dict):
        return aweme
    if body.get("aweme_id"):
        return body
    return _find_aweme(body)


def _capture_aweme(page, url: str, platform: str) -> dict | None:
    """打开分享页，优先用接口监听捕获作品数据，失败时解析页面内嵌数据。"""
    page.listen.start(DOUYIN_DETAIL_API, method="GET")
    try:
        page.get(url)
        try:
            page.wait.doc_loaded(timeout=DOUYIN_API_TIMEOUT)
        except Exception:
            pass
        package = page.listen.wait(timeout=DOUYIN_API_TIMEOUT)
        if isinstance(package, list):
            package = package[0] if package else None
        aweme = None
        if package is not None:
            body = _packet_body(package)
            if body:
                aweme = _aweme_from_packet(body)
        if aweme is None:
            log(platform, "未捕获接口数据，尝试解析页面内嵌数据 ...", "warn")
            aweme = find_aweme_from_html(page.html or "")
        return aweme
    finally:
        try:
            page.listen.stop()
        except Exception:
            pass


def fetch_video_info(share_url: str, platform: str = "douyin") -> DouyinInfo:
    """打开分享链接，捕获作品数据并返回无水印地址。"""
    url = extract_share_url(share_url)
    log(platform, f"提取到的链接：{url}")

    with _fetch_lock:  # 同一个页面不能并发操作
        aweme: dict | None = None
        failure: Exception | None = None
        for attempt in (1, 2):
            try:
                page = _get_page()
            except DouyinError:
                raise
            except Exception as exc:  # 浏览器启动失败：给出可读的原因
                raise DouyinError(f"浏览器启动失败：{exc}") from exc
            log(platform, "正在打开页面并等待视频数据 ...")
            try:
                aweme = _capture_aweme(page, url, platform)
                failure = None
                break
            except Exception as exc:  # 浏览器被关掉 / 页面崩溃 / 网络异常
                failure = exc
                close_browser()  # 页面状态可能异常，下次重建
                if attempt == 1:
                    log(
                        platform,
                        f"浏览器连接异常（{_first_line(str(exc))}），正在重启浏览器重试 ...",
                        "warn",
                    )
        if failure is not None:
            raise DouyinError(
                "浏览器连接失败（窗口可能已被关闭），重启后仍失败："
                f"{_first_line(str(failure))}"
            ) from failure

        if aweme is None:
            close_browser()  # 页面状态可能异常，下次重建
            raise DouyinError(
                "未获取到视频数据：可能需要登录/完成验证码，或链接已失效"
            )
        info = build_info(aweme)
        log(platform, f"解析到视频标题：{info.title}")
        return info
