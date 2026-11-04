"""HTTP 路由：B站 / 抖音的解析与下载接口。"""

from __future__ import annotations

import functools
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from flask import Blueprint, Response, jsonify, render_template, request

from . import bilibili, douyin
from .config import (
    APP_NAME,
    BILI_HEADERS,
    DOUYIN_HEADERS,
    DOWNLOAD_DIR,
    ENABLE_BROWSE_DIALOG,
    VERSION,
)
from .downloader import (
    DownloadError,
    create_session,
    download_file,
    extract_audio,
    make_temp_path,
    merge_audio_video,
)
from .events import PLATFORMS, bus, log
from .state import STATE
from .utils import ensure_dir, human_size, resolve_save_dir, sanitize_filename, unique_path

bp = Blueprint("api", __name__)

_browse_lock = threading.Lock()


# ===================== 工具函数 =====================
def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _fail(message: str, status: int = 400):
    return jsonify({"ok": False, "msg": message}), status


def _background(platform: str) -> Callable:
    """装饰器：把任务放到后台线程执行，结束后自动释放平台锁。"""
    def decorator(target: Callable[[], None]):
        @functools.wraps(target)
        def launcher(*args, **kwargs) -> None:
            def run() -> None:
                try:
                    target(*args, **kwargs)
                finally:
                    STATE.end_task(platform)

            threading.Thread(target=run, daemon=True, name=f"{platform}-worker").start()

        return launcher

    return decorator


def _quality_labels(options: list[dict]) -> list[str]:
    labels = []
    for option in options:
        desc = option.get("desc") or f"qn={option.get('qn')}"
        codec = option.get("codecs") or ""
        labels.append(f"{desc} · {codec}" if codec else desc)
    return labels


# ===================== 页面 =====================
@bp.get("/")
def index():
    return render_template(
        "index.html",
        app_name=APP_NAME,
        download_dir=str(DOWNLOAD_DIR),
        version=VERSION,
        browse_enabled=ENABLE_BROWSE_DIALOG,
    )


@bp.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "version": VERSION,
        "busy": {name: STATE.is_busy(name) for name in PLATFORMS},
        "logged_in": STATE.bili_logged_in,
        "download_dir": str(DOWNLOAD_DIR),
    })


# ===================== SSE 日志流 =====================
@bp.get("/api/stream/<platform>")
def stream(platform: str):
    if platform not in PLATFORMS:
        return _fail("未知平台", 404)

    def generate():
        channel = bus.subscribe(platform)
        try:
            yield "retry: 3000\n\n"
            yield "data: " + json.dumps({"type": "hello"}) + "\n\n"
            while True:
                try:
                    message = channel.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield "data: " + json.dumps(message, ensure_ascii=False) + "\n\n"
        finally:
            bus.unsubscribe(platform, channel)

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


# ===================== B站 =====================
@bp.get("/api/bili/status")
def bili_status():
    force = request.args.get("force") == "1"
    try:
        logged_in = STATE.cookie_status(force=force)
    except Exception as exc:  # 网络异常不应该让页面崩掉
        log("bili", f"登录状态检查失败：{exc}", "warn")
        logged_in = STATE.bili_logged_in
    return jsonify({"logged_in": logged_in})


@bp.post("/api/bili/login")
def bili_login():
    if not STATE.begin_task("bili"):
        return _fail("已有 B站任务在执行，请稍候", 409)

    @_background("bili")
    def worker():
        try:
            log("bili", "正在启动浏览器，请在窗口中完成登录 ...")
            jar = bilibili.login_via_selenium()
            if not jar:
                log("bili", "登录失败或超时，请重试或手动粘贴 Cookie", "error")
                bus.publish("bili", {"type": "login_status", "value": False})
                return
            STATE.save_cookies(jar)
            logged_in = STATE.cookie_status(force=True)
            if logged_in:
                log("bili", "登录成功，Cookie 已保存", "ok")
            else:
                log("bili", "已获取 Cookie，但校验未通过（可能未完成登录）", "warn")
            bus.publish("bili", {"type": "login_status", "value": logged_in})
        except bilibili.BiliError as exc:
            log("bili", f"自动登录失败：{exc}", "error")
            bus.publish("bili", {"type": "login_status", "value": False})
        except Exception as exc:
            log("bili", f"登录异常：{exc}", "error")
            bus.publish("bili", {"type": "login_status", "value": False})

    worker()
    return jsonify({"ok": True})


@bp.post("/api/bili/cookie")
def bili_save_cookie():
    cookie_str = str(_body().get("cookie") or "").strip()
    if not cookie_str:
        return _fail("Cookie 为空")
    jar = bilibili.cookies_from_string(cookie_str)
    if len(jar) == 0:
        return _fail("Cookie 格式不正确，应形如 SESSDATA=xxx; bili_jct=yyy")
    session = create_session(BILI_HEADERS)
    try:
        session.cookies = jar
        valid = bilibili.check_login(session)
    finally:
        session.close()
    if valid is None:
        return _fail("暂时无法连接 B站 校验 Cookie，请检查网络后重试")
    if not valid:
        return _fail("Cookie 无效或已过期，请重新登录")
    STATE.save_cookies(jar)
    log("bili", "Cookie 已保存并通过校验", "ok")
    return jsonify({"ok": True, "logged_in": True})


@bp.post("/api/bili/clear")
def bili_clear():
    if STATE.is_busy("bili"):
        return _fail("B站任务进行中，无法清除登录状态", 409)
    STATE.clear_cookies()
    log("bili", "已清除本地 Cookie")
    return jsonify({"ok": True})


@bp.post("/api/bili/parse")
def bili_parse():
    url = str(_body().get("url") or "").strip()
    if not url:
        return _fail("请输入视频链接")
    if not STATE.begin_task("bili"):
        return _fail("已有 B站任务在执行，请稍候", 409)

    @_background("bili")
    def worker():
        try:
            log("bili", f"开始解析：{url}")
            if not STATE.cookie_status():
                log("bili", "当前未登录，清晰度可能限制在 480P 以内", "warn")
            info = bilibili.fetch_video_info(STATE.bili_session, url)
            streams = bilibili.fetch_streams(STATE.bili_session, info.bvid, info.cid)
            options = [
                {
                    "qn": item.qn,
                    "desc": item.desc,
                    "codecs": item.codecs,
                    "url": item.url,
                    "backup_urls": item.backup_urls,
                    "bandwidth": item.bandwidth,
                }
                for item in streams.videos
            ]
            STATE.bili_video = {
                "bvid": info.bvid,
                "cid": info.cid,
                "title": info.title,
                "page": info.page,
                "options": options,
                "audio": None if streams.audio is None else {
                    "url": streams.audio.url,
                    "backup_urls": streams.audio.backup_urls,
                    "bandwidth": streams.audio.bandwidth,
                    "codecs": streams.audio.codecs,
                },
                "is_dash": streams.is_dash,
            }
            labels = _quality_labels(options)
            default_index = max(
                range(len(options)),
                key=lambda i: (options[i]["qn"], options[i]["bandwidth"]),
            ) if options else 0
            bus.publish("bili", {
                "type": "bili_parsed",
                "title": info.title,
                "qualities": labels,
                "default_index": default_index,
                "has_audio": streams.audio is not None,
            })
            log("bili", f"解析成功：{info.title}（{len(labels)} 个清晰度）", "ok")
        except Exception as exc:
            log("bili", f"解析失败：{exc}", "error")
            bus.publish("bili", {"type": "bili_parsed", "error": str(exc)})

    worker()
    return jsonify({"ok": True})


@bp.post("/api/bili/download")
def bili_download():
    body = _body()
    mode = str(body.get("mode") or "full")
    if mode not in ("full", "video_only", "audio_only"):
        return _fail("下载模式不正确")
    try:
        quality_index = int(body.get("quality_index", -1))
    except (TypeError, ValueError):
        quality_index = -1
    video = STATE.bili_video
    if not video:
        return _fail("请先解析视频")
    if not STATE.begin_task("bili"):
        return _fail("已有 B站任务在执行，请稍候", 409)

    @_background("bili")
    def worker():
        temp_files: list[Path] = []
        try:
            directory = ensure_dir(resolve_save_dir(body.get("save_dir")))
            title = sanitize_filename(video["title"])
            options = video["options"]
            index = quality_index
            if not 0 <= index < len(options):
                index = len(options) - 1
            option = options[index]
            audio = video.get("audio")
            bus.publish("bili", {"type": "progress", "value": 0})
            log("bili", f"已选择清晰度：{option['desc']}（{option['codecs'] or '默认编码'}）")

            if mode == "audio_only":
                if audio:
                    target = unique_path(directory / f"{title}.m4a")
                    download_file(audio["url"], target, "音频流", BILI_HEADERS, "bili",
                                  fallback_urls=audio.get("backup_urls"))
                else:
                    temp = make_temp_path(directory, ".mp4")
                    temp_files.append(temp)
                    download_file(option["url"], temp, "视频流", BILI_HEADERS, "bili",
                                  fallback_urls=option.get("backup_urls"))
                    log("bili", "该清晰度为音视频合流，正在提取音轨 ...")
                    target = extract_audio(temp, unique_path(directory / f"{title}.m4a"))
            elif mode == "video_only":
                target = unique_path(directory / f"{title}_无声.mp4")
                download_file(option["url"], target, "视频流", BILI_HEADERS, "bili",
                              fallback_urls=option.get("backup_urls"))
            else:
                target = unique_path(directory / f"{title}.mp4")
                if audio:
                    video_temp = make_temp_path(directory, ".video.m4s")
                    audio_temp = make_temp_path(directory, ".audio.m4s")
                    temp_files.extend([video_temp, audio_temp])
                    download_file(option["url"], video_temp, "视频流", BILI_HEADERS, "bili",
                                  fallback_urls=option.get("backup_urls"))
                    download_file(audio["url"], audio_temp, "音频流", BILI_HEADERS, "bili",
                                  fallback_urls=audio.get("backup_urls"))
                    log("bili", "正在合并音视频 ...")
                    merge_audio_video(video_temp, audio_temp, target)
                else:
                    download_file(option["url"], target, "视频流", BILI_HEADERS, "bili",
                                  fallback_urls=option.get("backup_urls"))

            STATE.register_file(target)
            size = human_size(target.stat().st_size) if target.exists() else ""
            log("bili", f"下载完成：{target}（{size}）", "ok")
            bus.publish("bili", {"type": "done", "path": str(target), "size": size})
        except Exception as exc:
            log("bili", f"下载失败：{exc}", "error")
            bus.publish("bili", {"type": "error", "msg": str(exc)})
        finally:
            for temp in temp_files:
                temp.unlink(missing_ok=True)

    worker()
    return jsonify({"ok": True})


# ===================== 抖音 =====================
@bp.post("/api/douyin/parse")
def douyin_parse():
    text = str(_body().get("text") or "").strip()
    if not text:
        return _fail("请粘贴分享内容")
    if not STATE.begin_task("douyin"):
        return _fail("已有抖音任务在执行，请稍候", 409)

    @_background("douyin")
    def worker():
        try:
            info = douyin.fetch_video_info(text, "douyin")
            STATE.douyin_video = {
                "title": info.title,
                "video_url": info.video_url,
                "audio_url": info.audio_url,
                "aweme_id": info.aweme_id,
            }
            bus.publish("douyin", {"type": "douyin_parsed", "title": info.title})
            log("douyin", "解析成功", "ok")
        except Exception as exc:
            log("douyin", f"解析失败：{exc}", "error")
            bus.publish("douyin", {"type": "douyin_parsed", "error": str(exc)})

    worker()
    return jsonify({"ok": True})


@bp.post("/api/douyin/download")
def douyin_download():
    body = _body()
    mode = str(body.get("mode") or "full")
    if mode not in ("full", "audio_only"):
        return _fail("下载模式不正确")
    info = STATE.douyin_video
    if not info:
        return _fail("请先解析视频")
    if not STATE.begin_task("douyin"):
        return _fail("已有抖音任务在执行，请稍候", 409)

    @_background("douyin")
    def worker():
        temp_files: list[Path] = []
        try:
            directory = ensure_dir(resolve_save_dir(body.get("save_dir")))
            title = sanitize_filename(info["title"])
            bus.publish("douyin", {"type": "progress", "value": 0})
            if mode == "full":
                target = unique_path(directory / f"{title}.mp4")
                download_file(info["video_url"], target, "视频", DOUYIN_HEADERS, "douyin")
            elif info.get("audio_url"):
                target = unique_path(directory / f"{title}.m4a")
                download_file(info["audio_url"], target, "音频", DOUYIN_HEADERS, "douyin")
            else:
                temp = make_temp_path(directory, ".mp4")
                temp_files.append(temp)
                download_file(info["video_url"], temp, "视频", DOUYIN_HEADERS, "douyin")
                log("douyin", "未找到独立音频流，正在从视频中提取音频 ...")
                target = extract_audio(temp, unique_path(directory / f"{title}.m4a"))

            STATE.register_file(target)
            size = human_size(target.stat().st_size) if target.exists() else ""
            log("douyin", f"下载完成：{target}（{size}）", "ok")
            bus.publish("douyin", {"type": "done", "path": str(target), "size": size})
        except Exception as exc:
            log("douyin", f"下载失败：{exc}", "error")
            bus.publish("douyin", {"type": "error", "msg": str(exc)})
        finally:
            for temp in temp_files:
                temp.unlink(missing_ok=True)

    worker()
    return jsonify({"ok": True})


# ===================== 本地交互 =====================
@bp.post("/api/browse")
def browse_dir():
    """弹出系统目录选择框（Windows 下可在请求线程中直接使用 tkinter）。"""
    if not ENABLE_BROWSE_DIALOG:
        return _fail("已通过 ENABLE_BROWSE_DIALOG=0 禁用目录选择")
    if not _browse_lock.acquire(blocking=False):
        return _fail("目录选择框已经打开", 409)
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askdirectory(
            parent=root, title="选择保存目录", initialdir=str(DOWNLOAD_DIR)
        )
        return jsonify({"ok": True, "dir": selected or ""})
    except Exception as exc:
        return _fail(f"无法打开目录选择框：{exc}", 500)
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
        _browse_lock.release()


@bp.post("/api/reveal")
def reveal_file():
    """在文件管理器中定位下载好的文件。"""
    raw = str(_body().get("path") or "").strip()
    if not raw:
        return _fail("缺少文件路径")
    target = Path(raw)
    if not STATE.is_produced(target):
        return _fail("只能打开本程序下载的文件")
    if not target.exists():
        return _fail("文件已不存在", 404)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(target)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent)])
    except OSError as exc:
        return _fail(f"无法打开文件管理器：{exc}", 500)
    return jsonify({"ok": True})
