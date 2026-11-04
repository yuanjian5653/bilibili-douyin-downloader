"""构建 Windows 单文件 exe。

用法::

    pip install pyinstaller
    python build_exe.py

产物：``dist/VideoDownloader.exe``，双击即可启动并在浏览器打开界面。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    spec = ROOT / "VideoDownloader.spec"
    if not spec.exists():
        print(f"找不到打包配置：{spec}")
        return 1
    if not (ROOT / "app.ico").exists():
        print("提示：缺少 app.ico，将使用默认图标（可运行 python scripts/make_icon.py 生成）")

    for folder in ("build", "dist"):
        shutil.rmtree(ROOT / folder, ignore_errors=True)

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", str(spec),
    ]
    print("执行：", " ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("打包失败，请查看上面的输出。")
        return result.returncode

    exe = ROOT / "dist" / "VideoDownloader.exe"
    if not exe.exists():
        print("打包完成但没有找到 exe，请检查 dist 目录。")
        return 1
    print(f"\n构建完成：{exe}")
    print(f"文件大小：{exe.stat().st_size / 1024 / 1024:.1f} MB")
    print("双击即可运行，首次启动约需几秒解包。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
