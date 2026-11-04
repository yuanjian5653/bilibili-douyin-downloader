"""下载任务与前端之间的实时事件总线（SSE 推送）。"""

from __future__ import annotations

import queue
import threading
import time

PLATFORMS: tuple[str, ...] = ("bili", "douyin")


class EventBus:
    """按平台分组的多订阅者事件总线。

    每个 SSE 连接对应一个独立的 :class:`queue.Queue`。为避免浏览器长时间
    不消费导致内存膨胀，队列满时丢弃最早的消息。
    """

    def __init__(self, max_queue_size: int = 500) -> None:
        self._subs: dict[str, list[queue.Queue]] = {name: [] for name in PLATFORMS}
        self._lock = threading.Lock()
        self._max_queue_size = max_queue_size

    def subscribe(self, platform: str) -> queue.Queue:
        if platform not in PLATFORMS:
            raise KeyError(f"未知平台：{platform}")
        channel: queue.Queue = queue.Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._subs[platform].append(channel)
        return channel

    def unsubscribe(self, platform: str, channel: queue.Queue) -> None:
        with self._lock:
            subscribers = self._subs.get(platform)
            if subscribers and channel in subscribers:
                subscribers.remove(channel)

    def publish(self, platform: str, message: dict) -> None:
        """发布消息。未知平台静默忽略，绝不因为推送失败打断下载线程。"""
        with self._lock:
            subscribers = list(self._subs.get(platform, ()))
        for channel in subscribers:
            try:
                channel.put_nowait(message)
            except queue.Full:
                try:
                    channel.get_nowait()  # 丢掉最旧的一条，保证新消息可以进入
                    channel.put_nowait(message)
                except (queue.Empty, queue.Full):
                    pass

    def subscriber_count(self, platform: str) -> int:
        with self._lock:
            return len(self._subs.get(platform, ()))


bus = EventBus()


def log(platform: str, message: str, level: str = "info") -> None:
    """同时输出到终端与前端日志面板。"""
    prefix = {"error": "[ERR]", "warn": "[WARN]", "ok": "[OK]"}.get(level, "[INFO]")
    print(f"[{time.strftime('%H:%M:%S')}][{platform}] {prefix} {message}", flush=True)
    bus.publish(platform, {"type": "log", "msg": message, "level": level})
