"""通用下载与 FFmpeg 音视频处理。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import (
    DOWNLOAD_CHUNK_SIZE,
    DOWNLOAD_RETRIES,
    DOWNLOAD_TIMEOUT,
    PROGRESS_INTERVAL,
)
from .events import log
from .utils import human_size


class DownloadError(RuntimeError):
    """下载失败，消息可直接展示给用户。"""


def create_session(headers: dict[str, str] | None = None,
                   retries: int = 0) -> requests.Session:
    """创建带连接复用与可选重试的 Session。"""
    session = requests.Session()
    if headers:
        session.headers.update(headers)
    if retries > 0:
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    return session


def _download_once(url: str, target: Path, desc: str, headers: dict[str, str],
                   platform: str, session: requests.Session,
                   timeout: int) -> int:
    with session.get(url, headers=headers, stream=True, timeout=timeout,
                     allow_redirects=True) as resp:
        if resp.status_code >= 400:
            raise DownloadError(f"{desc}下载失败：HTTP {resp.status_code}")
        total = int(resp.headers.get("content-length") or 0)
        downloaded = 0
        started = time.time()
        last_push = 0.0
        last_pct = -1.0
        with target.open("wb") as handle:
            for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                pct = downloaded / total * 100 if total else -1
                if now - last_push >= PROGRESS_INTERVAL and abs(pct - last_pct) >= 0.5:
                    last_push = now
                    last_pct = pct
                    _publish_progress(platform, pct, downloaded, total)
        if total and downloaded < total:
            raise DownloadError(
                f"{desc}下载不完整（{human_size(downloaded)}/{human_size(total)}）"
            )
        elapsed = max(time.time() - started, 1e-6)
        speed = human_size(downloaded / elapsed) + "/s"
        log(platform, f"{desc} 下载完成：{human_size(downloaded)}，平均 {speed}")
        _publish_progress(platform, 100.0, downloaded, total or downloaded)
        return downloaded


def _publish_progress(platform: str, pct: float, downloaded: int, total: int) -> None:
    from .events import bus

    bus.publish(platform, {
        "type": "progress",
        "value": max(0.0, min(100.0, pct)),
        "downloaded": downloaded,
        "total": total,
    })


def download_file(url: str, filepath: str | Path, desc: str, headers: dict[str, str],
                  platform: str, *, session: requests.Session | None = None,
                  fallback_urls: list[str] | None = None,
                  timeout: int = DOWNLOAD_TIMEOUT) -> Path:
    """下载到 ``filepath``。

    先写入 ``*.part`` 临时文件，成功后再原子改名，避免中断留下半截文件。
    主地址失败时会依次尝试 ``fallback_urls``（例如 B站返回的 backup_url）。
    """
    target = Path(filepath)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    candidates = [url] + [u for u in (fallback_urls or []) if u and u != url]
    own_session = session is None
    active_session = session or create_session(headers=headers)

    log(platform, f"开始下载 {desc} ...")
    last_error: Exception | None = None
    try:
        for index, candidate in enumerate(candidates):
            try:
                if index:
                    log(platform, f"{desc} 主地址失败，尝试备用地址 {index} ...", "warn")
                _download_once(candidate, part, desc, headers, platform,
                               active_session, timeout)
                os.replace(part, target)
                return target
            except (requests.RequestException, DownloadError, OSError) as exc:
                last_error = exc
                part.unlink(missing_ok=True)
                continue
        if isinstance(last_error, PermissionError):
            raise DownloadError(
                f"无法写入文件：{last_error}。保存目录可能被系统或安全软件保护"
                "（例如 Windows「受控文件夹访问」），请换一个目录后重试。"
            )
        raise DownloadError(f"{desc}下载失败：{last_error}")
    finally:
        part.unlink(missing_ok=True)
        if own_session:
            active_session.close()


def make_temp_path(directory: str | Path, suffix: str = ".part") -> Path:
    """在目标目录下生成唯一的临时文件路径（用于音视频分轨）。"""
    return Path(directory) / f".tmp-{uuid.uuid4().hex}{suffix}"


# ===================== FFmpeg =====================
_FFMPEG_EXE: str | None = None


def ffmpeg_exe() -> str:
    """返回可用的 ffmpeg 路径，优先使用 imageio-ffmpeg 内置的二进制。"""
    global _FFMPEG_EXE
    if _FFMPEG_EXE and Path(_FFMPEG_EXE).exists():
        return _FFMPEG_EXE
    try:
        import imageio_ffmpeg

        _FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - 依赖缺失
        raise DownloadError(
            "未找到 FFmpeg，无法合并音视频。请执行 pip install imageio-ffmpeg"
        ) from exc
    return _FFMPEG_EXE


def _run_ffmpeg(args: list[str], desc: str) -> None:
    exe = ffmpeg_exe()
    cmd = [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args]
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
            timeout=3600,
        )
    except FileNotFoundError as exc:
        raise DownloadError(f"{desc}失败：找不到 ffmpeg（{exe}）") from exc
    except subprocess.TimeoutExpired as exc:
        raise DownloadError(f"{desc}失败：处理超时") from exc
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()
        raise DownloadError(f"{desc}失败：{detail[-400:] or 'ffmpeg 返回非零状态'}")


def merge_audio_video(video_path: str | Path, audio_path: str | Path,
                      output_path: str | Path) -> Path:
    """把 B站分离的音视频轨合并成一个 mp4。

    默认直接复制音频流（B站音频本身就是 AAC，无需重编码）；如果封装失败
    再退回 AAC 重编码，兼容性更好。
    """
    video, audio, output = Path(video_path), Path(audio_path), Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    def _copy() -> None:
        _run_ffmpeg(["-i", str(video), "-i", str(audio), "-map", "0:v:0",
                     "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy",
                     "-movflags", "+faststart", str(output)], "合并音视频")

    try:
        _copy()
    except DownloadError:
        output.unlink(missing_ok=True)
        _run_ffmpeg(["-i", str(video), "-i", str(audio), "-map", "0:v:0",
                     "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                     "-b:a", "192k", str(output)], "重新编码合并音视频")
    return output


def extract_audio(video_path: str | Path, output_path: str | Path) -> Path:
    """从视频中提取音轨（不重编码 AAC）。"""
    video, output = Path(video_path), Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    try:
        _run_ffmpeg(["-i", str(video), "-vn", "-c:a", "copy", str(output)], "提取音频")
    except DownloadError:
        output.unlink(missing_ok=True)
        _run_ffmpeg(["-i", str(video), "-vn", "-c:a", "aac", "-b:a", "192k",
                     str(output)], "提取音频")
    return output
