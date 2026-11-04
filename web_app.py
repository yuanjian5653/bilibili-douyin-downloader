"""双平台视频下载器 —— 启动入口。

用法::

    python web_app.py

启动后会在浏览器中打开界面（默认 http://127.0.0.1:5000）。
"""

from __future__ import annotations

import sys
import threading
import time
import webbrowser

from app import create_app
from app.config import (
    APP_NAME,
    FLASK_DEBUG,
    FLASK_HOST,
    FLASK_PORT,
    OPEN_BROWSER,
    VERSION,
)

app = create_app()


def _open_browser(url: str) -> None:
    time.sleep(1.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _configure_console() -> None:
    """Windows 控制台默认 GBK，重定向为 UTF-8 避免中文/符号打印报错。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> int:
    _configure_console()
    url = f"http://{FLASK_HOST}:{FLASK_PORT}"
    print("=" * 56)
    print(f"  {APP_NAME} v{VERSION}")
    print(f"  界面地址：{url}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 56)

    if OPEN_BROWSER:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()

    try:
        app.run(host=FLASK_HOST, port=FLASK_PORT, threaded=True,
                debug=FLASK_DEBUG, use_reloader=False)
    except OSError as exc:
        print(f"\n启动失败：{exc}")
        print(f"端口 {FLASK_PORT} 可能已被占用，可设置环境变量 FLASK_PORT 换一个端口。")
        return 1
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
