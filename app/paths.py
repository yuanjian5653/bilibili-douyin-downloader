"""路径解析：区分「程序/资源目录」与「可写数据目录」。

打包成 exe 后：

* 只读资源（模板、静态文件、内置 ffmpeg）在 PyInstaller 解包目录 ``_MEIPASS``；
* 可写数据（Cookie、下载目录、日志、浏览器临时目录）优先放在 exe 所在目录，
  不可写时退回 ``%LOCALAPPDATA%\\VideoDownloader`` 或系统临时目录。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


def is_frozen() -> bool:
    """当前是否运行在 PyInstaller 打包后的 exe 中。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """exe 所在目录（未打包时是项目根目录）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """只读资源根目录。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return Path(__file__).resolve().parent.parent


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".probe-{os.getpid()}-{time.time_ns()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


_data_dir: Path | None = None


def data_dir() -> Path:
    """返回可写数据目录（首次调用时探测并缓存）。"""
    global _data_dir
    if _data_dir is not None:
        return _data_dir

    candidates = [app_dir()]
    local_app = os.getenv("LOCALAPPDATA")
    if local_app:
        candidates.append(Path(local_app) / "VideoDownloader")
    candidates.append(Path(tempfile.gettempdir()) / "VideoDownloader")

    for candidate in candidates:
        if _is_writable(candidate):
            _data_dir = candidate
            return candidate
    _data_dir = app_dir()
    return _data_dir
