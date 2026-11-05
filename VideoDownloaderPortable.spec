# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成便携版目录 ``dist/VideoDownloaderPortable``。

用法::

    python build_exe.py --portable

产物是 exe + ``_internal`` 目录（onedir），启动比单文件版快，也不依赖系统
临时目录解包；发布时把整个目录压缩成 ``VideoDownloader-portable-win64.zip``。
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("app/templates", "app/templates"),
    ("app/static", "app/static"),
]
datas += collect_data_files("imageio_ffmpeg")
# selenium 的 Selenium Manager 可执行文件在包内，缺了自动登录就没法下载驱动
datas += collect_data_files("selenium")

# selenium 4.x 的 selenium.webdriver 包是惰性导入（_LAZY_IMPORTS + __getattr__），
# 静态分析看不到 edge.webdriver / chrome.webdriver，必须显式收集全部子模块。
hiddenimports = collect_submodules("selenium")
hiddenimports += collect_submodules("DrissionPage")

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
    [],
    exclude_binaries=True,
    name="VideoDownloaderPortable",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app.ico",
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VideoDownloaderPortable",
)
