"""B站视频解析：链接识别、视频信息、播放地址、Cookie 登录。"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests
from requests.cookies import RequestsCookieJar

from .config import (
    BASE_DIR,
    BILI_FNVAL,
    BILI_HEADERS,
    BILI_QN,
    LOGIN_URL,
    PLAYURL_API,
    QUALITY_DESC,
    REQUEST_TIMEOUT,
    SELENIUM_LOGIN_TIMEOUT,
    TEST_API,
    VIEW_API,
)
from .utils import extract_first_url, resource_path

_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AVID_RE = re.compile(r"/av(\d+)", re.IGNORECASE)
_PAGE_RE = re.compile(r"[?&]p=(\d+)")
_SHORT_HOSTS = ("b23.tv", "bili2233.cn")


class BiliError(RuntimeError):
    """B站接口错误，消息可直接展示给用户。"""


@dataclass
class VideoInfo:
    bvid: str
    aid: int
    cid: int
    title: str
    page: int = 1
    page_count: int = 1


@dataclass
class StreamOption:
    qn: int
    desc: str
    codecs: str
    url: str
    bandwidth: int = 0
    backup_urls: list[str] = field(default_factory=list)


@dataclass
class Streams:
    videos: list[StreamOption]
    audio: StreamOption | None = None
    is_dash: bool = True


# ===================== 链接解析 =====================
def extract_video_id(url: str) -> dict:
    """从各种形式的 B站链接中提取 bvid/avid 与分P序号。

    支持 ``/video/BVxxxx``、``/video/av123``、``?p=2``、``b23.tv`` 短链。
    短链需要传入 session 才能解析（见 :func:`resolve_short_url`）。
    """
    text = (url or "").strip()
    if not text:
        raise BiliError("请输入视频链接")
    page_match = _PAGE_RE.search(text)
    page = int(page_match.group(1)) if page_match else 1
    if page < 1:
        page = 1
    bvid_match = _BVID_RE.search(text)
    if bvid_match:
        return {"bvid": bvid_match.group(1), "aid": None, "page": page}
    aid_match = _AVID_RE.search(text)
    if aid_match:
        return {"bvid": None, "aid": int(aid_match.group(1)), "page": page}
    if re.search(r"/(ep|ss)\d+", text):
        raise BiliError("暂不支持番剧/课程链接，请使用普通稿件链接")
    raise BiliError("无法识别视频 ID，请检查链接（例如 https://www.bilibili.com/video/BV1xx411c7mD）")


def is_short_link(url: str) -> bool:
    return any(host in (url or "") for host in _SHORT_HOSTS)


def resolve_short_url(session: requests.Session, url: str) -> str:
    """展开 b23.tv 短链，返回真实地址。"""
    candidate = extract_first_url(url) or url
    try:
        resp = session.get(candidate, headers=BILI_HEADERS, timeout=REQUEST_TIMEOUT,
                           allow_redirects=True)
    except requests.RequestException as exc:
        raise BiliError(f"短链解析失败：{exc}") from exc
    final = getattr(resp, "url", "") or candidate
    if final == candidate:
        # 有些短链返回 200 页面内嵌跳转，这里再兜一层
        match = re.search(r'https?://(?:www\.)?bilibili\.com/video/(BV[0-9A-Za-z]{10}|av\d+)',
                          resp.text or "")
        if match:
            return match.group(0)
    return final


# ===================== 页面数据解析 =====================
def extract_json_object(text: str, start: int) -> str | None:
    """从 ``start`` 处的 ``{`` 开始，按大括号配对截取一个完整的 JSON 对象。

    比正则 ``(\\{.*?\\});`` 可靠：能正确处理字符串里的 ``};`` 与嵌套对象。
    """
    if start < 0 or start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
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
                return text[start:index + 1]
    return None


def parse_initial_state(html: str) -> dict | None:
    """解析页面里的 ``window.__INITIAL_STATE__``（接口不可用时的兜底）。"""
    marker = "__INITIAL_STATE__"
    index = html.find(marker)
    if index < 0:
        return None
    brace = html.find("{", index)
    if brace < 0:
        return None
    raw = extract_json_object(html, brace)
    if not raw:
        return None
    return json.loads(raw.replace("undefined", "null"))


# ===================== 接口调用 =====================
def _get_json(session: requests.Session, url: str, params: dict | None = None,
              desc: str = "接口") -> dict:
    try:
        resp = session.get(url, params=params, headers=BILI_HEADERS,
                           timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise BiliError(f"{desc}请求失败：{exc}") from exc
    if resp.status_code != 200:
        raise BiliError(f"{desc}返回异常状态码：{resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise BiliError(f"{desc}返回数据无法解析（可能触发了风控，请稍后重试）") from exc


def fetch_video_info(session: requests.Session, url: str) -> VideoInfo:
    """解析视频基本信息与目标分P的 cid。"""
    if is_short_link(url):
        url = resolve_short_url(session, url)
    parsed = extract_video_id(url)

    params = {"bvid": parsed["bvid"]} if parsed["bvid"] else {"aid": parsed["aid"]}
    payload = _get_json(session, VIEW_API, params, "视频信息接口")
    code = payload.get("code")
    if code != 0:
        message = payload.get("message") or "未知错误"
        if code == -404:
            raise BiliError("视频不存在或已删除")
        if code in (-403, -10403):
            raise BiliError("该视频有访问权限限制（可能需要登录或大会员）")
        raise BiliError(f"视频信息接口返回错误：{message}（code={code}）")

    data = payload.get("data") or {}
    pages = data.get("pages") or []
    page = parsed["page"]
    if pages:
        if page > len(pages):
            raise BiliError(f"分P序号超出范围（共 {len(pages)} P）")
        cid = pages[page - 1].get("cid") or data.get("cid")
        title = data.get("title") or "未命名视频"
        if len(pages) > 1:
            part = pages[page - 1].get("part") or ""
            if part:
                title = f"{title} - P{page} {part}"
    else:
        cid = data.get("cid")
        title = data.get("title") or "未命名视频"

    if not cid:
        raise BiliError("未能获取视频 cid")
    return VideoInfo(
        bvid=data.get("bvid") or parsed["bvid"] or "",
        aid=int(data.get("aid") or parsed["aid"] or 0),
        cid=int(cid),
        title=title.strip(),
        page=page,
        page_count=max(len(pages), 1),
    )


def codec_label(codecs: str) -> str:
    codecs = (codecs or "").lower()
    if codecs.startswith(("avc", "h264")):
        return "AVC"
    if codecs.startswith(("hev", "hvc", "h265")):
        return "HEVC"
    if codecs.startswith("av01"):
        return "AV1"
    if codecs.startswith(("mp4a", "aac")):
        return "AAC"
    if codecs.startswith("ec-3"):
        return "EAC3"
    return codecs.split(".")[0].upper() or "未知"


def quality_desc(qn: int, support_formats: list[dict] | None = None) -> str:
    for item in support_formats or []:
        try:
            if int(item.get("quality", -1)) == qn:
                return (item.get("new_description") or item.get("display_desc")
                        or QUALITY_DESC.get(qn, f"未知({qn})"))
        except (TypeError, ValueError):
            continue
    return QUALITY_DESC.get(qn, f"未知({qn})")


def _dedupe_videos(options: list[StreamOption]) -> list[StreamOption]:
    """同一清晰度可能有 AVC/HEVC/AV1 多个编码，全部保留；重复编码取最高码率。"""
    best: dict[tuple[int, str], StreamOption] = {}
    for option in options:
        key = (option.qn, codec_label(option.codecs))
        current = best.get(key)
        if current is None or option.bandwidth > current.bandwidth:
            best[key] = option
    # 清晰度从低到高，同清晰度内码率从高到低（AVC 通常排在最前，兼容性最好）
    return sorted(best.values(), key=lambda item: (item.qn, -item.bandwidth))


def fetch_streams(session: requests.Session, bvid: str, cid: int) -> Streams:
    """获取 DASH 播放地址；清晰度从低到高排序，音频取最高码率。"""
    params = {
        "bvid": bvid,
        "cid": cid,
        "qn": BILI_QN,
        "fnval": BILI_FNVAL,
        "fnver": 0,
        "fourk": 1,
    }
    payload = _get_json(session, PLAYURL_API, params, "播放地址接口")
    code = payload.get("code")
    if code != 0:
        message = payload.get("message") or "未知错误"
        if code in (-403, -10403, -404):
            raise BiliError("无法获取播放地址：该清晰度需要登录或大会员权限，请先登录")
        raise BiliError(f"播放地址接口返回错误：{message}（code={code}）")

    data = payload.get("data") or {}
    support_formats = data.get("support_formats") or []
    dash = data.get("dash")

    if dash:
        videos: list[StreamOption] = []
        for item in dash.get("video") or []:
            url = item.get("baseUrl") or item.get("base_url")
            if not url:
                continue
            qn = int(item.get("id") or 0)
            videos.append(StreamOption(
                qn=qn,
                desc=quality_desc(qn, support_formats),
                codecs=codec_label(item.get("codecs", "")),
                url=url,
                bandwidth=int(item.get("bandwidth") or 0),
                backup_urls=list(item.get("backupUrl") or item.get("backup_url") or []),
            ))
        if not videos:
            raise BiliError("未找到可用的视频流")

        audio_candidates: list[StreamOption] = []
        for item in dash.get("audio") or []:
            url = item.get("baseUrl") or item.get("base_url")
            if not url:
                continue
            audio_candidates.append(StreamOption(
                qn=int(item.get("id") or 0),
                desc="音频",
                codecs=codec_label(item.get("codecs", "")),
                url=url,
                bandwidth=int(item.get("bandwidth") or 0),
                backup_urls=list(item.get("backupUrl") or item.get("backup_url") or []),
            ))
        audio = max(audio_candidates, key=lambda item: item.bandwidth, default=None)
        return Streams(videos=_dedupe_videos(videos), audio=audio, is_dash=True)

    # 兜底：非 DASH（老视频或接口降级），音视频已合在一起
    durl = data.get("durl") or []
    if not durl:
        raise BiliError("未找到可用的视频流（可能需要登录后重试）")
    if len(durl) > 1:
        raise BiliError("该视频为分段流，暂不支持；请登录后使用 DASH 清晰度重试")
    qn = int(data.get("quality") or 0)
    url = durl[0].get("url")
    if not url:
        raise BiliError("未找到可用的视频地址")
    return Streams(
        videos=[StreamOption(
            qn=qn,
            desc=quality_desc(qn, support_formats),
            codecs="",
            url=url,
            backup_urls=list(durl[0].get("backup_url") or []),
        )],
        audio=None,
        is_dash=False,
    )


# ===================== 登录 =====================
def check_login(session: requests.Session) -> bool | None:
    """检查 Cookie 是否有效。网络异常时返回 ``None``（无法判断）。"""
    try:
        resp = session.get(TEST_API, headers=BILI_HEADERS, timeout=REQUEST_TIMEOUT)
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None
    if payload.get("code") == -101:
        return False
    return bool((payload.get("data") or {}).get("isLogin"))


def cookies_from_string(cookie_str: str) -> RequestsCookieJar:
    """解析浏览器里复制的 Cookie 字符串（也兼容带 ``Cookie:`` 前缀）。"""
    text = (cookie_str or "").strip()
    if text.lower().startswith("cookie:"):
        text = text[7:].strip()
    jar = RequestsCookieJar()
    for item in text.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key, value = key.strip(), value.strip().strip('"')
        if key:
            jar.set(key, value, domain=".bilibili.com", path="/")
    return jar


def _cookies_to_jar(cookies: list[dict]) -> RequestsCookieJar:
    jar = RequestsCookieJar()
    for cookie in cookies:
        domain = cookie.get("domain") or ".bilibili.com"
        if "bilibili.com" not in domain:
            if "biligame" not in domain:
                continue
            domain = ".bilibili.com"
        jar.set(cookie["name"], cookie["value"], domain=domain,
                path=cookie.get("path", "/"))
    return jar


# ===================== 浏览器（自动登录） =====================
RUNTIME_DIR = BASE_DIR / ".runtime"


def _first_line(text: str, limit: int = 200) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[0][:limit] if lines else "未知错误"


def _ensure_writable(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".probe-{os.getpid()}-{time.time_ns()}"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        probe.unlink(missing_ok=True)
    return path


def prepare_browser_dirs(base_dir: Path | None = None, *,
                         fallback_to_temp: bool = True) -> tuple[Path, Path]:
    """创建浏览器专用的用户数据目录与临时目录。

    msedgedriver / Edge 默认会在系统 ``TEMP`` 下创建临时用户目录，在 TEMP 不可写
    （受限账户、清理策略、沙箱环境）时会直接失败：``cannot create temp dir for
    user data dir``。这里改为写在程序目录的 ``.runtime`` 下，并让驱动进程的
    ``TEMP/TMP/TMPDIR`` 也指向该目录；如果程序目录不可写，再退回系统临时目录。
    """
    base = Path(base_dir) if base_dir is not None else RUNTIME_DIR
    base = base.expanduser().resolve()
    candidates = [base]
    if fallback_to_temp:
        candidates.append(Path(tempfile.gettempdir()).resolve() / "video-downloader")
    errors: list[str] = []
    for candidate in candidates:
        try:
            temp_dir = _ensure_writable(candidate / "temp")
            profile_dir = _ensure_writable(candidate / f"profile-{uuid.uuid4().hex[:8]}")
            return profile_dir, temp_dir
        except OSError as exc:
            errors.append(f"{candidate}（{_first_line(str(exc), 80)}）")
    raise BiliError(
        "无法创建浏览器临时目录，自动登录不可用。请从普通终端 / PyCharm 启动本程序，"
        "或在界面里手动粘贴 Cookie。已尝试：" + "；".join(errors)
    )


def _service_env(temp_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("TEMP", "TMP", "TMPDIR"):
        env[key] = str(temp_dir)
    return env


def _browser_args(profile_dir: Path, temp_dir: Path, headless: bool = False) -> list[str]:
    args = [
        "--disable-blink-features=AutomationControlled",
        f"--user-data-dir={profile_dir}",
        f"--disk-cache-dir={Path(temp_dir) / 'cache'}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        "--window-size=1200,900",
    ]
    if headless:
        args.append("--headless=new")
    return args


def _start_browser(profile_dir: Path, temp_dir: Path, headless: bool = False):
    """依次尝试 Edge（Selenium Manager）→ 本地 msedgedriver → Chrome。

    返回可用的 WebDriver；全部失败时抛出 :class:`BiliError`，消息里带上每次尝试的原因。
    """
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.edge.service import Service as EdgeService

    env = _service_env(temp_dir)
    local_driver = resource_path("msedgedriver.exe")
    attempts: list[tuple[str, Callable[[], object]]] = []

    def edge_options() -> EdgeOptions:
        options = EdgeOptions()
        for arg in _browser_args(profile_dir, temp_dir, headless):
            options.add_argument(arg)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        return options

    attempts.append((
        "Edge（Selenium Manager）",
        lambda: webdriver.Edge(options=edge_options(), service=EdgeService(env=env)),
    ))
    if Path(local_driver).exists():
        # 本地驱动通常与已安装的浏览器版本匹配，优先尝试可避免 Selenium Manager
        # 使用缓存里的旧版本驱动（或因无网络下载失败而卡住）
        attempts.insert(0, (
            "Edge（本地 msedgedriver）",
            lambda: webdriver.Edge(
                options=edge_options(),
                service=EdgeService(executable_path=local_driver, env=env),
            ),
        ))

    try:
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService
    except ImportError:  # pragma: no cover - 理论不会发生
        ChromeOptions = None  # type: ignore[assignment]

    if ChromeOptions is not None:
        def chrome_options() -> "ChromeOptions":
            options = ChromeOptions()
            for arg in _browser_args(profile_dir, temp_dir, headless):
                options.add_argument(arg)
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            return options

        attempts.append((
            "Chrome（Selenium Manager）",
            lambda: webdriver.Chrome(options=chrome_options(), service=ChromeService(env=env)),
        ))

    errors: list[str] = []
    for name, factory in attempts:
        driver = None
        try:
            driver = factory()
            # 浏览器有时能创建会话但窗口立刻退出，先加载空白页确认可用
            driver.set_page_load_timeout(30)
            driver.get("about:blank")
        except Exception as exc:
            reason = _first_line(str(exc))
            errors.append(f"{name}：{reason}")
            print(f"[bili] {name} 启动失败：{reason}", flush=True)
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            continue
        print(f"[bili] 已启动浏览器：{name}", flush=True)
        return driver

    raise BiliError("所有浏览器都启动失败，请手动粘贴 Cookie。原因：" + "；".join(errors))


def login_via_selenium(timeout: int = SELENIUM_LOGIN_TIMEOUT) -> RequestsCookieJar | None:
    """打开浏览器让用户扫码/登录，成功后返回 Cookie。

    与旧实现相比做了三件事：

    * 使用程序目录下的独立用户数据目录与 TEMP，避免
      ``cannot create temp dir for user data dir``；
    * 依次尝试 Edge（Selenium Manager）→ 本地 msedgedriver → Chrome；
    * 失败时抛出带原因的 :class:`BiliError`，而不是静默返回 ``None``。

    登录超时返回 ``None``。
    """
    try:
        from selenium import webdriver  # noqa: F401
    except ImportError as exc:
        raise BiliError("未安装 selenium，无法自动登录（pip install selenium）") from exc

    profile_dir, temp_dir = prepare_browser_dirs()
    driver = None
    try:
        driver = _start_browser(profile_dir, temp_dir)
        try:
            driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
        except Exception:
            pass
        try:
            driver.set_page_load_timeout(60)
            driver.get(LOGIN_URL)
        except Exception as exc:
            raise BiliError(f"打开登录页失败：{_first_line(str(exc))}") from exc
        print(f"[bili] 请在浏览器窗口中扫码或登录（最长等待 {timeout} 秒）", flush=True)

        # 轮询 Cookie，比只等 URL 变化更可靠（扫码登录不一定跳转）
        deadline = time.time() + timeout
        jar: RequestsCookieJar | None = None
        while time.time() < deadline:
            time.sleep(1)
            try:
                cookie_list = driver.get_cookies()
            except Exception:
                break
            names = {cookie.get("name") for cookie in cookie_list}
            if {"SESSDATA", "bili_jct"} & names:
                jar = _cookies_to_jar(cookie_list)
                if len(jar) > 0:
                    break
        print("[bili] 已获取登录 Cookie" if jar else "[bili] 等待登录超时", flush=True)
        return jar
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        shutil.rmtree(profile_dir, ignore_errors=True)
