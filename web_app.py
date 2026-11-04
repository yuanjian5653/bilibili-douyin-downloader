"""双平台视频下载器 —— 启动入口。

源码运行::

    python web_app.py

打包后双击 ``VideoDownloader.exe`` 即可，会自动在本机启动服务并打开浏览器
（默认 http://127.0.0.1:5000）。
"""

from __future__ import annotations

import ctypes
import io
import socket
import sys
import threading
import time
import webbrowser

FROZEN = bool(getattr(sys, "frozen", False))


class _DevNull(io.TextIOBase):
    """窗口模式下 sys.stdout 可能为 None，用空实现兜底，避免 print 崩溃。"""

    def write(self, text):  # noqa: D401 - 简单透传
        return len(text)

    def flush(self) -> None:
        pass


if FROZEN and sys.stdout is None:  # pragma: no cover - 仅打包运行
    sys.stdout = _DevNull()
    sys.stderr = _DevNull()

from app import create_app  # noqa: E402
from app.config import (  # noqa: E402
    APP_NAME,
    DATA_DIR,
    FLASK_DEBUG,
    FLASK_HOST,
    FLASK_PORT,
    OPEN_BROWSER,
    VERSION,
)


def _redirect_output_to_log() -> None:
    """窗口模式没有控制台，把输出写到数据目录的 app.log，方便排查。"""
    if not FROZEN:
        return
    try:
        stream = (DATA_DIR / "app.log").open(
            "a", encoding="utf-8", errors="replace", buffering=1
        )
    except OSError:
        stream = _DevNull()
    sys.stdout = stream
    sys.stderr = stream
    print(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 {APP_NAME} v{VERSION} ===")


def _message(text: str, error: bool = True) -> None:
    """没有控制台时用系统弹窗告知错误。"""
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


def _open_browser(url: str) -> None:
    time.sleep(1.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _port_in_use(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


app = create_app()


def main() -> int:
    _redirect_output_to_log()
    url = f"http://{FLASK_HOST}:{FLASK_PORT}"
    print(f"{APP_NAME} v{VERSION}")
    print(f"数据目录：{DATA_DIR}")
    print(f"界面地址：{url}")

    if _port_in_use(FLASK_HOST, FLASK_PORT):
        # 重复双击等情况：直接把已运行的界面打开，避免端口冲突报错
        print(f"端口 {FLASK_PORT} 已在监听，打开已有界面。")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        return 0

    if OPEN_BROWSER:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    try:
        app.run(host=FLASK_HOST, port=FLASK_PORT, threaded=True,
                debug=FLASK_DEBUG, use_reloader=False)
    except OSError as exc:
        _message(
            f"启动失败：{exc}\n\n端口 {FLASK_PORT} 可能已被占用，"
            f"可以设置环境变量 FLASK_PORT 换一个端口。\n\n日志：{DATA_DIR / 'app.log'}"
        )
        return 1
    except KeyboardInterrupt:
        print("\n已停止。")
    except Exception as exc:  # pragma: no cover - 兜底
        _message(f"启动失败：{exc}\n\n日志：{DATA_DIR / 'app.log'}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
