"""与业务无关的小工具函数。"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

from . import config
from .config import FILENAME_MAX_LEN

# Windows 不允许出现在文件名中的字符；连续非法字符合并为一个下划线
_INVALID_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')
_WHITESPACE_RE = re.compile(r"\s+")
# 文本中的第一个 http(s) 链接（排除中文标点，避免把「，谢谢」吞进链接）
_URL_RE = re.compile(r"https?://[^\s<>\"'，。；：！？、（）【】]+", re.IGNORECASE)
# Windows 保留设备名，作为文件名会导致创建失败
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def resource_path(relative_path: str) -> str:
    """返回资源文件的绝对路径。

    打包后优先找 exe 同目录（便于用户放置自己的 ``msedgedriver.exe``），
    再找 PyInstaller 解包目录；未打包时按项目根目录解析。
    """
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / relative_path)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / relative_path)
    else:
        candidates.append(Path(__file__).resolve().parent.parent / relative_path)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0])


def extract_first_url(text: str) -> str | None:
    """提取文本中的第一个 http(s) 链接，去掉尾部的常见标点。"""
    if not text:
        return None
    match = _URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?，。；：！？、")


def sanitize_filename(name: str, max_length: int = FILENAME_MAX_LEN,
                      default: str = "untitled") -> str:
    """把任意标题转换成安全的、可用于 Windows/macOS/Linux 的文件名。

    - 替换非法字符与控制字符
    - 压缩空白、去掉首尾空白和点号（Windows 会静默丢弃结尾的点）
    - 规避 Windows 设备名（CON/PRN/...）
    - 按字符数截断，避免超过路径长度限制
    """
    text = unicodedata.normalize("NFC", str(name or ""))
    text = _INVALID_CHARS_RE.sub("_", text)
    text = _WHITESPACE_RE.sub(" ", text).strip(" .")
    # 结尾的点 / 空格会让 Windows 创建文件失败
    text = text.rstrip(" .")
    if not text:
        return default
    stem = text.split(".")[0].strip().upper()
    if stem in _RESERVED_NAMES:
        text = f"_{text}"
    if len(text) > max_length:
        text = text[:max_length].rstrip(" .")
    return text or default


def unique_path(path: Path) -> Path:
    """如果文件已存在，则追加 (1)、(2) … 避免覆盖已有文件。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem} ({os.getpid()}){suffix}")


def human_size(size: float | int | None) -> str:
    """把字节数格式化成人类可读的字符串。"""
    if not size or size < 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def resolve_save_dir(raw: str | None) -> Path:
    """把前端传来的保存目录解析成绝对路径，空值回退到默认下载目录。"""
    text = str(raw or "").strip()
    if not text:
        return Path(config.DOWNLOAD_DIR)
    return config.resolve_path(text)


def ensure_dir(path: Path | str) -> Path:
    """确保目录存在且可写，否则抛出带说明的 ValueError。"""
    directory = Path(path).expanduser()
    if directory.exists() and not directory.is_dir():
        raise ValueError(f"保存路径不是文件夹：{directory}")
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"无法创建目录 {directory}：{exc}") from exc
    if not os.access(directory, os.W_OK):
        raise ValueError(f"目录不可写：{directory}")
    return directory
