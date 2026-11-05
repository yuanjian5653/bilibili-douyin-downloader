"""utils 模块单元测试。"""

from __future__ import annotations

import os
import shutil
import unittest

from app import config
from app.utils import (
    ensure_dir,
    extract_first_url,
    human_size,
    resolve_save_dir,
    sanitize_filename,
    unique_path,
)
from tests.helpers import AppTestCase, make_temp_dir


class SanitizeFilenameTests(unittest.TestCase):
    def test_basics(self):
        cases = [
            ("正常标题", "正常标题"),
            ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
            ("多   个    空白", "多 个 空白"),
            ("  前后空格  ", "前后空格"),
            ("结尾有点...", "结尾有点"),
            ("含控制符\x01\x02文本", "含控制符_文本"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(sanitize_filename(raw), expected)

    def test_empty_returns_default(self):
        self.assertEqual(sanitize_filename(""), "untitled")
        self.assertEqual(sanitize_filename("   ...  "), "untitled")
        self.assertEqual(sanitize_filename(None, default="video"), "video")

    def test_reserved_windows_names(self):
        self.assertEqual(sanitize_filename("CON"), "_CON")
        self.assertEqual(sanitize_filename("nul"), "_nul")
        self.assertEqual(sanitize_filename("COM1"), "_COM1")
        self.assertTrue(sanitize_filename("aux.mp4").startswith("_aux"))

    def test_truncates_to_limit(self):
        self.assertEqual(len(sanitize_filename("标" * 200, max_length=30)), 30)

    def test_keeps_extension_untouched(self):
        self.assertEqual(sanitize_filename("视频.最终版.mp4"), "视频.最终版.mp4")


class MiscUtilsTests(AppTestCase):
    def test_extract_first_url(self):
        text = "7.43 复制打开抖音 https://v.douyin.com/iRNBho6u/ 看看视频"
        self.assertEqual(extract_first_url(text), "https://v.douyin.com/iRNBho6u/")
        self.assertEqual(
            extract_first_url("链接：https://example.com/a?b=1，谢谢。"),
            "https://example.com/a?b=1",
        )
        self.assertIsNone(extract_first_url("没有链接"))
        self.assertIsNone(extract_first_url(""))

    def test_human_size(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(None), "0 B")
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(1024), "1.0 KB")
        self.assertEqual(human_size(1536), "1.5 KB")
        self.assertEqual(human_size(1024 ** 3), "1.0 GB")

    def test_unique_path(self):
        first = self.tmp_path / "video.mp4"
        first.write_bytes(b"1")
        second = unique_path(first)
        self.assertEqual(second.name, "video (1).mp4")
        second.write_bytes(b"2")
        self.assertEqual(unique_path(first).name, "video (2).mp4")

    def test_ensure_dir(self):
        directory = ensure_dir(self.tmp_path / "a" / "b")
        self.assertTrue(directory.is_dir())
        self.assertTrue(os.access(directory, os.W_OK))

        file_path = self.tmp_path / "not-a-dir"
        file_path.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            ensure_dir(file_path)

    def test_ensure_dir_leaves_no_probe_file(self):
        directory = ensure_dir(self.tmp_path / "clean")
        self.assertEqual(list(directory.iterdir()), [])

    def test_resolve_save_dir(self):
        raw = make_temp_dir("resolve-")
        self.addCleanup(shutil.rmtree, raw, True)
        target = raw / "downloads"
        self.patch(config, "DOWNLOAD_DIR", target)
        self.assertEqual(resolve_save_dir(""), target)
        self.assertTrue(resolve_save_dir("video").is_absolute())
        self.assertEqual(resolve_save_dir(str(raw / "x")), raw / "x")


if __name__ == "__main__":
    unittest.main()
