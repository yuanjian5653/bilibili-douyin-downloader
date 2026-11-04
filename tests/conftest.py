"""pytest 公共夹具：隔离全局状态、提供本地 HTTP 测试服务。"""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAYLOAD = b"x" * (256 * 1024 + 17)


class _Handler(BaseHTTPRequestHandler):
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


@pytest.fixture(scope="session")
def http_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def isolate_state(monkeypatch, tmp_path):
    """每个用例都从干净状态开始，且把 Cookie 文件指向临时目录。"""
    from app import state as state_module
    from app.events import bus
    from app.state import STATE

    monkeypatch.setattr(state_module, "COOKIE_FILE", tmp_path / "cookies.pkl")
    STATE.reset()
    for platform in ("bili", "douyin"):
        for channel in list(bus._subs[platform]):
            bus.unsubscribe(platform, channel)
    yield
    STATE.reset()
