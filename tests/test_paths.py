"""路径解析单元测试（源码运行与打包运行共用的逻辑）。"""

from __future__ import annotations

import unittest
from pathlib import Path

from app import config, paths


class PathTests(unittest.TestCase):
    def test_not_frozen_in_tests(self):
        self.assertFalse(paths.is_frozen())

    def test_app_dir_is_project_root(self):
        self.assertEqual(paths.app_dir(), Path(paths.__file__).resolve().parents[1])

    def test_bundle_dir_exists(self):
        self.assertTrue(paths.bundle_dir().is_dir())

    def test_data_dir_writable(self):
        directory = paths.data_dir()
        self.assertTrue(directory.is_dir())
        probe = directory / ".test-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()

    def test_config_paths_are_absolute(self):
        self.assertTrue(config.DOWNLOAD_DIR.is_absolute())
        self.assertTrue(config.COOKIE_FILE.is_absolute())
        self.assertTrue(config.RUNTIME_DIR.is_absolute())

    def test_resolve_path_relative_to_data_dir(self):
        resolved = config.resolve_path("downloads")
        self.assertEqual(resolved, config.DATA_DIR / "downloads")


if __name__ == "__main__":
    unittest.main()
