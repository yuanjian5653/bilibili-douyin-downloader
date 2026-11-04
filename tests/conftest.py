"""pytest 兼容入口：确保项目根目录在 ``sys.path`` 中。

测试主体使用标准库 ``unittest``（``python -m unittest discover -s tests -t .``），
本文件只在用 pytest 收集用例时提供路径兜底，不依赖 pytest。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
