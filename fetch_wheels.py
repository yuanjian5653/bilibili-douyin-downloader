"""下载 PyInstaller 及其依赖的 wheel 到 .pkg 目录（离线安装用）。"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

DEST = Path(".pkg")

PACKAGES = {
    "pyinstaller": ("py3-none-win_amd64.whl",),
    "pyinstaller-hooks-contrib": ("py3-none-any.whl",),
    "altgraph": ("py3-none-any.whl", "py2.py3-none-any.whl"),
    "pefile": ("py3-none-any.whl",),
    "pywin32-ctypes": ("py2.py3-none-any.whl", "py3-none-any.whl"),
    "packaging": ("py3-none-any.whl",),
}

session = requests.Session()
session.headers["User-Agent"] = "dsh-agent"

DEST.mkdir(parents=True, exist_ok=True)


def main() -> int:
    for project, suffixes in PACKAGES.items():
        data = session.get(f"https://pypi.org/pypi/{project}/json", timeout=30).json()
        version = data["info"]["version"]
        candidates = [
            item for item in data["urls"]
            if item["filename"].endswith(tuple(suffixes))
        ]
        if not candidates:
            print(f"[跳过] {project} {version}: 没有匹配的 wheel")
            continue
        item = candidates[0]
        target = DEST / item["filename"]
        if target.exists() and target.stat().st_size == item["size"]:
            print(f"[已存在] {target.name}")
            continue
        print(f"[下载] {project} {version} -> {item['filename']} ({item['size'] // 1024} KB)")
        with session.get(item["url"], timeout=120, stream=True) as resp:
            resp.raise_for_status()
            with target.open("wb") as handle:
                for chunk in resp.iter_content(1 << 16):
                    handle.write(chunk)
        if target.stat().st_size != item["size"]:
            print(f"[错误] 大小不一致: {target}")
            return 1
    print("完成，文件：")
    for path in sorted(DEST.iterdir()):
        print(f"  {path.name}  {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
