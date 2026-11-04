"""进程级共享状态：Cookie、会话、已解析的视频信息、任务互斥。"""

from __future__ import annotations

import pickle
import threading
import time
from pathlib import Path
from typing import Any

import requests

from . import bilibili
from .config import BILI_HEADERS, COOKIE_FILE, COOKIE_CHECK_TTL
from .downloader import create_session
from .events import PLATFORMS


class AppState:
    """所有跨请求共享的数据都集中在这里，并用锁保护。

    原来的实现把状态散落在全局变量里，双击按钮就会启动两个下载任务
    写同一个文件；这里用 ``begin_task`` / ``end_task`` 保证每个平台
    同一时间只跑一个任务。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._check_lock = threading.Lock()

        self.bili_session: requests.Session = create_session(headers=BILI_HEADERS)
        self.bili_logged_in: bool = False
        self._cookie_checked_at: float = 0.0

        self.bili_video: dict[str, Any] | None = None
        self.douyin_video: dict[str, Any] | None = None

        self._busy: dict[str, bool] = {name: False for name in PLATFORMS}
        self._produced_files: set[str] = set()

        self._load_cookies()

    # ---------- Cookie ----------
    def _load_cookies(self) -> None:
        path = Path(COOKIE_FILE)
        if not path.exists():
            return
        try:
            with path.open("rb") as handle:
                jar = pickle.load(handle)
        except Exception as exc:  # 文件损坏 / 版本不兼容
            print(f"[state] 读取 Cookie 文件失败，已忽略：{exc}")
            return
        if isinstance(jar, requests.cookies.RequestsCookieJar):
            # 只加载不校验：真正的登录状态在首次 /api/bili/status 时确认
            self.bili_session.cookies = jar
            self.bili_logged_in = False
            self._cookie_checked_at = 0.0

    def apply_cookies(self, jar: requests.cookies.RequestsCookieJar) -> None:
        with self._lock:
            self.bili_session.cookies = jar
            self.bili_logged_in = True
            self._cookie_checked_at = time.time()

    def save_cookies(self, jar: requests.cookies.RequestsCookieJar) -> None:
        with open(COOKIE_FILE, "wb") as handle:
            pickle.dump(jar, handle)
        self.apply_cookies(jar)

    def clear_cookies(self) -> None:
        with self._lock:
            try:
                Path(COOKIE_FILE).unlink(missing_ok=True)
            except OSError:
                pass
            self.bili_session.cookies.clear()
            self.bili_logged_in = False
            self._cookie_checked_at = 0.0

    def cookie_status(self, force: bool = False) -> bool:
        """带缓存的登录状态检查，避免每次刷新页面都打一次网络请求。"""
        if not force and COOKIE_CHECK_TTL > 0:
            with self._lock:
                age = time.time() - self._cookie_checked_at
                if age < COOKIE_CHECK_TTL:
                    return self.bili_logged_in
        # 串行化并发检查，避免同时发出多个请求
        with self._check_lock:
            with self._lock:
                age = time.time() - self._cookie_checked_at
                if not force and COOKIE_CHECK_TTL > 0 and age < COOKIE_CHECK_TTL:
                    return self.bili_logged_in
                has_cookies = len(self.bili_session.cookies) > 0
            if not has_cookies:
                with self._lock:
                    self.bili_logged_in = False
                    self._cookie_checked_at = time.time()
                return False
            ok = bilibili.check_login(self.bili_session)
            with self._lock:
                # 网络异常时 check_login 返回 None，保留上一次的结论
                if ok is not None:
                    self.bili_logged_in = ok
                self._cookie_checked_at = time.time()
                return self.bili_logged_in

    # ---------- 任务互斥 ----------
    def begin_task(self, platform: str) -> bool:
        with self._lock:
            if self._busy[platform]:
                return False
            self._busy[platform] = True
            return True

    def end_task(self, platform: str) -> None:
        with self._lock:
            self._busy[platform] = False

    def is_busy(self, platform: str) -> bool:
        with self._lock:
            return self._busy[platform]

    # ---------- 已生成文件（用于「打开所在文件夹」的白名单校验） ----------
    def register_file(self, path: str | Path) -> None:
        with self._lock:
            self._produced_files.add(str(Path(path).resolve()))
            if len(self._produced_files) > 200:
                self._produced_files = set(list(self._produced_files)[-100:])

    def is_produced(self, path: str | Path) -> bool:
        with self._lock:
            return str(Path(path).resolve()) in self._produced_files

    def reset(self) -> None:
        """清空运行期状态（测试用，也可用于「重置」场景）。"""
        with self._lock:
            self.bili_session.cookies.clear()
            self.bili_logged_in = False
            self._cookie_checked_at = 0.0
            self.bili_video = None
            self.douyin_video = None
            for name in self._busy:
                self._busy[name] = False
            self._produced_files.clear()


STATE = AppState()
