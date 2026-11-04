"""测试公共设施：本地 HTTP 服务与全局状态隔离。

测试只依赖标准库，可以直接运行::

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 临时目录放在项目内，避免受系统临时目录权限（沙箱）影响
TEMP_ROOT = ROOT / ".test-tmp"

PAYLOAD = b"x" * (256 * 1024 + 17)


def make_temp_dir(name: str = "case-") -> Path:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=name, dir=str(TEMP_ROOT)))


class _PayloadHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - 标准库接口
        if self.path.startswith("/payload"):
            self._send(PAYLOAD, len(PAYLOAD))
        elif self.path.startswith("/partial"):
            # 声明完整长度但只发送一部分，用于验证完整性校验
            self._send(PAYLOAD[:1000], len(PAYLOAD))
        else:
            self.send_error(404)

    def _send(self, body: bytes, declared: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(declared))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def log_message(self, *args) -> None:  # 静默
        pass


@contextlib.contextmanager
def http_server():
    """启动一个只提供 /payload、/partial 的本地 HTTP 服务。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PayloadHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


def wait_for(channel: queue.Queue, wanted: str, timeout: float = 10.0) -> dict:
    """从事件队列里等待指定类型的事件，跳过日志与进度。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            message = channel.get(timeout=0.2)
        except queue.Empty:
            continue
        if message.get("type") == wanted:
            return message
    raise AssertionError(f"没有收到 {wanted} 事件")


class AppTestCase(unittest.TestCase):
    """为每个用例准备临时目录、干净的全局状态与独立的 Cookie 文件。"""

    def setUp(self) -> None:
        from app import state as state_module
        from app.events import bus
        from app.state import STATE

        self.tmp_path = make_temp_dir()
        self.addCleanup(shutil.rmtree, self.tmp_path, True)

        self._original_cookie_file = state_module.COOKIE_FILE
        state_module.COOKIE_FILE = self.tmp_path / "cookies.pkl"
        self.addCleanup(self._restore_cookie_file, state_module)

        STATE.reset()
        self.addCleanup(STATE.reset)
        for platform in ("bili", "douyin"):
            for channel in list(bus._subs[platform]):
                bus.unsubscribe(platform, channel)
        self.addCleanup(self._unsubscribe_all, bus)

    def _restore_cookie_file(self, state_module) -> None:
        state_module.COOKIE_FILE = self._original_cookie_file

    def _unsubscribe_all(self, bus) -> None:
        for platform in ("bili", "douyin"):
            for channel in list(bus._subs[platform]):
                bus.unsubscribe(platform, channel)

    def patch(self, target, attribute: str, value):
        """等价于 pytest 的 monkeypatch.setattr。"""
        patcher = mock.patch.object(target, attribute, value)
        patched = patcher.start()
        self.addCleanup(patcher.stop)
        return patched

    def patch_dict(self, mapping: dict, attribute: str, value):
        patcher = mock.patch.dict(mapping, {attribute: value})
        patcher.start()
        self.addCleanup(patcher.stop)
        return patcher
