"""事件总线测试。"""

from __future__ import annotations

import queue
import unittest

from app.events import EventBus, bus, log


class EventBusTests(unittest.TestCase):
    def test_subscribe_publish_delivery(self):
        own = EventBus()
        channel = own.subscribe("bili")
        own.publish("bili", {"type": "log", "msg": "hi"})
        self.assertEqual(channel.get_nowait(), {"type": "log", "msg": "hi"})

    def test_platforms_are_isolated(self):
        own = EventBus()
        bili_channel = own.subscribe("bili")
        douyin_channel = own.subscribe("douyin")
        own.publish("bili", "for-bili")
        self.assertEqual(bili_channel.get_nowait(), "for-bili")
        self.assertTrue(douyin_channel.empty())

    def test_multiple_subscribers_all_receive(self):
        own = EventBus()
        first = own.subscribe("douyin")
        second = own.subscribe("douyin")
        own.publish("douyin", {"n": 1})
        self.assertEqual(first.get_nowait(), {"n": 1})
        self.assertEqual(second.get_nowait(), {"n": 1})

    def test_unknown_platform_on_subscribe_raises(self):
        with self.assertRaises(KeyError):
            EventBus().subscribe("kuaishou")

    def test_publish_unknown_platform_is_silent(self):
        EventBus().publish("unknown", {"x": 1})

    def test_unsubscribe_stops_delivery(self):
        own = EventBus()
        channel = own.subscribe("bili")
        own.unsubscribe("bili", channel)
        own.publish("bili", "later")
        with self.assertRaises(queue.Empty):
            channel.get_nowait()

    def test_unsubscribe_unknown_channel_is_safe(self):
        own = EventBus()
        channel = queue.Queue()
        own.unsubscribe("bili", channel)

    def test_queue_overflow_drops_oldest(self):
        own = EventBus(max_queue_size=2)
        channel = own.subscribe("bili")
        for index in range(5):
            own.publish("bili", index)
        self.assertEqual([channel.get_nowait() for _ in range(2)], [3, 4])
        with self.assertRaises(queue.Empty):
            channel.get_nowait()

    def test_log_publishes_message(self):
        channel = bus.subscribe("bili")
        try:
            log("bili", "hello", "warn")
            message = channel.get_nowait()
        finally:
            bus.unsubscribe("bili", channel)
        self.assertEqual(message["type"], "log")
        self.assertEqual(message["msg"], "hello")
        self.assertEqual(message["level"], "warn")

    def test_subscriber_count(self):
        own = EventBus()
        own.subscribe("bili")
        self.assertEqual(own.subscriber_count("bili"), 1)


if __name__ == "__main__":
    unittest.main()
