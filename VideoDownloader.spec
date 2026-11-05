# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成单文件 ``dist/VideoDownloader.exe``。

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
# selenium 的 Selenium Manager 可执行文件在包内，缺了自动登录就没法下载驱动
datas += collect_data_files("selenium")

# selenium 4.x 的 selenium.webdriver 包是惰性导入（_LAZY_IMPORTS + __getattr__）：
# webdriver.Edge / webdriver.Chrome 只是字典里的字符串，PyInstaller 的静态分析
# 看不到 selenium.webdriver.edge.webdriver 之类的模块，打包后会报
# “No module named 'selenium.webdriver.edge.webdriver'”（Edge 与 Chrome 同时失效）。
# 因此这里显式收集全部子模块，配合 app/bilibili.py 里的全路径 import。
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
