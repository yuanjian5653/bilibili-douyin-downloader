"""全局配置。

所有配置项都可以通过环境变量覆盖，也支持项目根目录（或 exe 同目录）下的
``.env`` 文件（需要安装 ``python-dotenv``）。相对路径统一相对于可写数据目录
解析：未打包时是项目根目录，打包后是 exe 所在目录（不可写时退回用户目录），
因此双击 exe 也能找到 Cookie 文件与下载目录。
"""

from __future__ import annotations

import os
from pathlib import Path

from .paths import app_dir, data_dir

try:  # pragma: no cover - 可选依赖
    from dotenv import load_dotenv

    load_dotenv(app_dir() / ".env")
    load_dotenv()
except ImportError:  # pragma: no cover
    pass


APP_NAME = "双平台视频下载器"
VERSION = "3.2.1"

# 程序目录（exe 所在目录 / 项目根目录）与可写数据目录
BASE_DIR = app_dir()
DATA_DIR = data_dir()
RUNTIME_DIR = DATA_DIR / ".runtime"


def _env_str(key: str, default: str) -> str:
    value = os.getenv(key)
    return default if value is None or not value.strip() else value.strip()


def _env_int(key: str, default: int, *, minimum: int | None = None,
             maximum: int | None = None) -> int:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "y")


def resolve_path(raw: str | os.PathLike[str]) -> Path:
    """把配置里的路径解析为绝对路径（相对路径基于可写数据目录）。"""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = DATA_DIR / path
    return path


# ===== 路径配置 =====
COOKIE_FILE = resolve_path(_env_str("BILI_COOKIE_FILE", "bilibili_cookies.pkl"))
DOWNLOAD_DIR = resolve_path(_env_str("DOWNLOAD_DIR", "downloads"))

# ===== Web 服务 =====
FLASK_HOST = _env_str("FLASK_HOST", "127.0.0.1")
FLASK_PORT = _env_int("FLASK_PORT", 5000, minimum=1, maximum=65535)
FLASK_DEBUG = _env_bool("FLASK_DEBUG", False)
OPEN_BROWSER = _env_bool("OPEN_BROWSER", True)

# ===== 网络请求 =====
REQUEST_TIMEOUT = _env_int("REQUEST_TIMEOUT", 20, minimum=1)
DOWNLOAD_TIMEOUT = _env_int("DOWNLOAD_TIMEOUT", 60, minimum=1)
DOWNLOAD_CHUNK_SIZE = 64 * 1024
DOWNLOAD_RETRIES = _env_int("DOWNLOAD_RETRIES", 2, minimum=0, maximum=5)
PROGRESS_INTERVAL = 0.25  # 进度推送最小间隔（秒），避免刷爆 SSE

# ===== 文件名 =====
FILENAME_MAX_LEN = _env_int("FILENAME_MAX_LEN", 80, minimum=16, maximum=200)

# ===== B站 =====
LOGIN_URL = "https://passport.bilibili.com/login"
TEST_API = "https://api.bilibili.com/x/web-interface/nav"
VIEW_API = "https://api.bilibili.com/x/web-interface/view"
PLAYURL_API = "https://api.bilibili.com/x/player/playurl"
SELENIUM_LOGIN_TIMEOUT = _env_int("SELENIUM_LOGIN_TIMEOUT", 300, minimum=30)
COOKIE_CHECK_TTL = _env_int("COOKIE_CHECK_TTL", 60, minimum=0)
# fnval: dash(16) + 4K(64) + HDR(256) + 杜比(512) + 8K(1024) + AV1(2048) = 4048
BILI_FNVAL = _env_int("BILI_FNVAL", 4048, minimum=16)
BILI_QN = _env_int("BILI_QN", 127, minimum=16)

# 清晰度 id -> 描述，接口未返回 support_formats 时兜底
QUALITY_DESC = {
    6: "240P",
    16: "360P",
    32: "480P",
    64: "720P",
    74: "720P 60帧",
    80: "1080P",
    112: "1080P+",
    116: "1080P 60帧",
    120: "4K",
    125: "HDR",
    126: "杜比视界",
    127: "8K",
}

# ===== 抖音 =====
# 0 表示自动分配端口，避免和已运行的浏览器冲突
DOUYIN_BROWSER_PORT = _env_int("DOUYIN_BROWSER_PORT", 0, minimum=0, maximum=65535)
DOUYIN_API_TIMEOUT = _env_int("DOUYIN_API_TIMEOUT", 30, minimum=5)
DOUYIN_HEADLESS = _env_bool("DOUYIN_HEADLESS", False)
DOUYIN_BROWSER_PATH = _env_str("DOUYIN_BROWSER_PATH", "")

# ===== 界面 =====
ENABLE_BROWSE_DIALOG = _env_bool("ENABLE_BROWSE_DIALOG", True)

# ===== 请求头 =====
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
BILI_HEADERS = {
    **HEADERS,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}
DOUYIN_HEADERS = {
    **HEADERS,
    "Referer": "https://www.douyin.com/",
}
