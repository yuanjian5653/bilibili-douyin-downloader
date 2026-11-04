"""校验 Release 资源完整性，并修正发布说明里的便携版文件名。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import requests

TOKEN = os.environ["GH_TOKEN"]
REPO = "yuanjian5653/bilibili-douyin-downloader"
TAG = "v3.2.0"

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "dsh-agent",
})

release = session.get(
    f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}", timeout=30
).json()

body = release.get("body", "")
if "VideoDownloader-portable-win64.zip` | 便携版：解压后运行里面的 `VideoDownloader.exe`" in body:
    body = body.replace(
        "便携版：解压后运行里面的 `VideoDownloader.exe`",
        "便携版：解压后运行里面的 `VideoDownloaderPortable.exe`",
    )
    patched = session.patch(release["url"], json={"body": body}, timeout=30)
    print("发布说明已更新:", patched.status_code)
else:
    print("发布说明无需修改")

for name, local in (
    ("VideoDownloader.exe", Path("dist/VideoDownloader.exe")),
    ("VideoDownloader-portable-win64.zip", Path("dist/VideoDownloader-portable-win64.zip")),
):
    asset = next((a for a in release["assets"] if a["name"] == name), None)
    if asset is None:
        print("缺少资源:", name)
        continue
    local_hash = hashlib.sha256(local.read_bytes()).hexdigest()
    print(f"{name}: 远端 {asset['size'] / 1024 / 1024:.1f} MB，本地 {local.stat().st_size / 1024 / 1024:.1f} MB")
    digest = hashlib.sha256()
    total = 0
    with session.get(asset["browser_download_url"], stream=True, timeout=900) as response:
        response.raise_for_status()
        for chunk in response.iter_content(1 << 20):
            digest.update(chunk)
            total += len(chunk)
    remote_hash = digest.hexdigest()
    print(f"  下载校验：{total / 1024 / 1024:.1f} MB，sha256 一致 = {remote_hash == local_hash}")
    print(f"  {asset['browser_download_url']}")

print("CHECK DONE")
