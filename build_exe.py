"""构建 Windows 可执行文件（单文件版或便携版）。

用法::

    pip install pyinstaller
    python build_exe.py              # 单文件：dist/VideoDownloader.exe
    python build_exe.py --portable   # 便携版：dist/VideoDownloaderPortable/

便携版是 exe + ``_internal`` 目录（onedir），启动更快，也不依赖系统临时目录
解包，发布时把整个目录压成 ``VideoDownloader-portable-win64.zip`` 即可。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 模式 -> (spec 文件名, 产物路径)
MODES = {
    "onefile": ("VideoDownloader.spec", Path("dist") / "VideoDownloader.exe"),
    "portable": (
        "VideoDownloaderPortable.spec",
        Path("dist") / "VideoDownloaderPortable" / "VideoDownloaderPortable.exe",
    ),
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    portable = "--portable" in argv
    mode = "portable" if portable else "onefile"
    spec_name, exe_relative = MODES[mode]

    spec = ROOT / spec_name
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

    exe = ROOT / exe_relative
    if not exe.exists():
        print(f"打包完成但没有找到 {exe}，请检查 dist 目录。")
        return 1
    print(f"\n构建完成：{exe}")
    print(f"文件大小：{exe.stat().st_size / 1024 / 1024:.1f} MB")
    if portable:
        print(f"整个目录可直接拷贝运行：{exe.parent}")
        print("发布时把该目录压缩成 VideoDownloader-portable-win64.zip 即可。")
    else:
        print("双击即可运行，首次启动约需几秒解包。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
