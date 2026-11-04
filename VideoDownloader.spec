# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成单文件 VideoDownloader.exe。

用法::

    python build_exe.py
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("app/templates", "app/templates"),
    ("app/static", "app/static"),
]
# imageio-ffmpeg 自带 ffmpeg 可执行文件，必须一起打包
datas += collect_data_files("imageio_ffmpeg")

hiddenimports = collect_submodules("DrissionPage")
hiddenimports += [
    "selenium.webdriver.edge.service",
    "selenium.webdriver.edge.options",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.chrome.options",
]

a = Analysis(
    ["web_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "numpy", "pandas", "matplotlib", "PIL", "pyecharts", "redis", "pymysql"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VideoDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app.ico",
    version="version_info.txt",
)
