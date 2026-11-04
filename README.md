# 双平台视频下载器（B站 + 抖音）

[![Tests](https://img.shields.io/badge/tests-93%20passed-brightgreen)](tests)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

一个带本地 Web 界面的视频下载工具：**B站** 支持多清晰度、分P、DASH 音视频合并；**抖音** 支持分享文案一键解析、无水印下载。启动后自动打开浏览器，所有操作都在页面里完成，不需要记命令行参数。

> ⚠️ **免责声明**：本项目仅用于学习与个人备份，请只下载你拥有版权或已获得授权的内容，并遵守 B站 / 抖音的用户协议与当地法律法规。请勿用于商业用途或二次分发。因使用本工具产生的一切后果由使用者自行承担。

---

## ✨ 功能

- **浏览器界面**：深色主题、响应式布局，手机浏览器也能操作
- **B站**
  - 扫码登录（Edge）或手动粘贴 Cookie，Cookie 本地加密保存只需登录一次
  - 清晰度可选 360P ~ 8K，自动列出 AVC / HEVC / AV1 各编码
  - 完整视频 / 仅视频（无声） / 仅音频三种模式
  - 自动识别 `BV` 号、`av` 号、`?p=` 分P、`b23.tv` 短链
- **抖音**
  - 直接粘贴「复制链接」得到的整段文案，自动提取链接
  - 无水印视频下载、音频单独提取
  - 接口捕获失败时自动回退解析页面内嵌数据
- **下载体验**
  - SSE 实时日志与进度条，终端和网页同步输出
  - 断点式临时文件：失败不会留下半截文件
  - 主地址失败自动切换备用 CDN 地址
  - 内置 FFmpeg（`imageio-ffmpeg`），无需手动安装
- **工程质量**：模块化拆分、类型标注、93 个不联网的单元测试

---

## 📸 界面预览

> 建议放一张截图：把图片保存为 `docs/screenshot.png`，然后取消下面这行的注释。

<!-- ![界面预览](docs/screenshot.png) -->

---

## 🚀 快速开始

### 环境要求

| 项目 | 要求 |
| --- | --- |
| Python | 3.10 及以上 |
| 操作系统 | Windows 10/11（主支持）；macOS / Linux 可运行，但自动登录与目录选择框依赖桌面环境 |
| 浏览器 | Edge（B站自动登录）、Chrome 或 Edge（抖音解析） |

### 安装

```bash
git clone https://github.com/yuanjian5653/bilibili-douyin-downloader.git
cd bilibili-douyin-downloader

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

### 运行

```bash
python web_app.py
```

默认打开 <http://127.0.0.1:5000>。端口被占用时设置环境变量即可：

```bash
set FLASK_PORT=5050            # Windows CMD
$env:FLASK_PORT=5050           # PowerShell
export FLASK_PORT=5050         # bash
```

也可以复制 `.env.example` 为 `.env` 统一管理配置（需 `python-dotenv`，已包含在依赖里）。

### 打包成 exe（可选）

```bash
pip install pyinstaller
pyinstaller -F -w -n VideoDownloader ^
  --add-data "app/templates;app/templates" ^
  --add-data "app/static;app/static" ^
  web_app.py
```

生成的程序在 `dist/VideoDownloader.exe`。若电脑上没有 Edge WebDriver，可把 `msedgedriver.exe` 放在 exe 同目录，程序会自动回退使用它。

---

## 📖 使用说明

### B站

1. 点击「自动登录 (Edge)」，在弹出的浏览器里扫码或账号登录；也可以把浏览器里的 Cookie 字符串粘贴到输入框后点「验证并保存」。
   - 不登录也能解析，但清晰度通常被限制在 480P 以内。
2. 粘贴视频链接，点「解析」，页面会显示标题与清晰度列表（默认选中最高清晰度）。
3. 选择模式与保存目录，点「开始下载」。完成后可直接点「打开所在文件夹」。

> 登录态保存在项目目录的 `bilibili_cookies.pkl`，已被 `.gitignore` 忽略，不会上传到仓库。

### 抖音

1. 在抖音 App 里点「分享 → 复制链接」，把整段文案粘贴到文本框。
2. 点「解析」，程序会启动浏览器并捕获作品数据（首次启动较慢）。
3. 选择「完整视频」或「仅音频」，点「开始下载」。

> 如果提示需要验证，请在自动打开的浏览器窗口里完成一次验证/登录后再试；浏览器实例会复用，后续解析更快。

---

## 🧱 项目结构

```
biliblil_and_douyin_app/
├── web_app.py                 # 启动入口（python web_app.py）
├── app/
│   ├── __init__.py            # Flask 应用工厂
│   ├── config.py              # 全部配置（支持环境变量 / .env）
│   ├── routes.py              # HTTP 接口与任务编排
│   ├── state.py               # 全局状态、任务互斥、Cookie 缓存
│   ├── events.py              # 事件总线（SSE 推送）
│   ├── downloader.py          # 通用下载、重试、FFmpeg 合并
│   ├── bilibili.py            # B站链接解析、播放地址、扫码登录
│   ├── douyin.py              # 抖音链接提取、接口监听、页面兜底解析
│   ├── utils.py               # 文件名清洗、路径处理等
│   ├── templates/index.html   # 页面模板
│   └── static/
│       ├── css/style.css
│       └── js/app.js
├── tests/                     # 标准库 unittest 测试（不联网）
├── requirements.txt
├── pyproject.toml
├── .env.example
└── LICENSE
```

### 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 页面 |
| GET | `/api/health` | 健康检查与版本信息 |
| GET | `/api/stream/<bili\|douyin>` | SSE 日志/进度流 |
| GET | `/api/bili/status` | 登录状态（带缓存，`?force=1` 强制刷新） |
| POST | `/api/bili/login` | 打开 Edge 扫码登录 |
| POST | `/api/bili/cookie` | 校验并保存手动粘贴的 Cookie |
| POST | `/api/bili/clear` | 清除 Cookie |
| POST | `/api/bili/parse` | 解析视频信息与清晰度 |
| POST | `/api/bili/download` | 下载（`full` / `video_only` / `audio_only`） |
| POST | `/api/douyin/parse` | 解析分享文案 |
| POST | `/api/douyin/download` | 下载（`full` / `audio_only`） |
| POST | `/api/browse` | 弹出系统目录选择框 |
| POST | `/api/reveal` | 在文件管理器中定位文件（仅限本程序下载的文件） |

---

## ⚙️ 配置

所有配置项都在 `app/config.py`，可用环境变量或 `.env` 覆盖：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLASK_HOST` / `FLASK_PORT` | `127.0.0.1` / `5000` | 监听地址与端口 |
| `OPEN_BROWSER` | `1` | 启动后是否自动开浏览器 |
| `DOWNLOAD_DIR` | `downloads` | 默认下载目录（相对路径基于项目根目录） |
| `REQUEST_TIMEOUT` | `20` | 普通接口超时（秒） |
| `DOWNLOAD_TIMEOUT` | `60` | 下载超时（秒） |
| `DOWNLOAD_RETRIES` | `2` | 网络错误重试次数 |
| `FILENAME_MAX_LEN` | `80` | 文件名最大长度，避免超 Windows 路径限制 |
| `BILI_COOKIE_FILE` | `bilibili_cookies.pkl` | Cookie 保存路径 |
| `SELENIUM_LOGIN_TIMEOUT` | `300` | 扫码登录等待上限（秒） |
| `COOKIE_CHECK_TTL` | `60` | 登录状态检查缓存（秒），0 表示每次都检查 |
| `BILI_FNVAL` | `4048` | 期望的清晰度能力位（DASH+4K+HDR+杜比+8K+AV1） |
| `DOUYIN_BROWSER_PORT` | `0` | `0` 为自动分配端口，避免和已开浏览器冲突 |
| `DOUYIN_API_TIMEOUT` | `30` | 等待抖音数据接口的超时（秒） |
| `DOUYIN_HEADLESS` | `0` | 抖音浏览器是否无头运行 |
| `DOUYIN_BROWSER_PATH` | 空 | 指定浏览器路径，一般留空 |
| `ENABLE_BROWSE_DIALOG` | `1` | 是否允许弹出目录选择框 |

---

## 🐞 本次整理修复的问题

重构前的版本是一个 1100 行的单文件脚本，本次做了模块化拆分，并修掉了下面这些坑：

| # | 问题 | 修复方式 |
| --- | --- | --- |
| 1 | 页面里的下载目录写的是 `{{DOWNLOAD_DIR}}`：`Response(INDEX_HTML)` 不经过模板渲染，用户在界面上看到的是字面量 | 改用 `render_template`，模板变量真正生效 |
| 2 | CSS 里有三条声明写在 `body {}` 之外，属于无效样式 | 重写样式表，分离 `style.css` |
| 3 | `quality_index` 未做类型/范围校验，前端传空值直接 500；闭包内重新赋值还会触发 `UnboundLocalError` | 显式校验并回退到最高清晰度，改用局部变量 |
| 4 | 同一清晰度只按 `id` 去重，HEVC / AV1 选项被丢掉，用户无法选择编码 | 按（清晰度, 编码）去重，同编码取最高码率 |
| 5 | `os.rename` 在目标文件已存在时（Windows）抛异常 | 用 `os.replace`，并通过 `unique_path` 自动改名不覆盖 |
| 6 | 下载没有超时和重试，写到一半失败会留下损坏的半截文件 | 加超时/重试，先写 `.part` 再原子改名，失败清理 |
| 7 | 进度事件每条 chunk 都推送，一次下载刷出上万条 SSE 消息 | 按时间 + 百分比节流 |
| 8 | 全局可变状态无锁，双击按钮会并发写同一批文件 | 状态集中在 `AppState` 加锁，并加平台级任务互斥（忙时返回 409） |
| 9 | 用正则 `{.*?};` 抓 B站 `__INITIAL_STATE__`，遇到字符串里的 `};` 就截断 | 改为大括号配对解析，且主流程改用官方 `view` 接口 |
| 10 | 抖音 `ChromiumOptions().set_local_port(9222).save()` 会把端口写进全局配置，且固定端口容易冲突 | 默认 `auto_port()`，不再 `.save()`；浏览器实例复用 |
| 11 | 抖音只靠监听 `aweme/detail` 接口，分享页不调用接口时必然超时失败 | 监听失败后回退解析 `_ROUTER_DATA` / `RENDER_DATA` |
| 12 | 每次打开页面都请求一次 B站 nav 接口校验 Cookie，离线时还误判为失效 | 登录状态带 TTL 缓存；网络异常保留上次结论 |
| 13 | 只有 `/video/BV...` 能被识别，`b23.tv` 短链、`av` 号、分P 全部失败 | 补齐短链展开、`av` 号、`?p=` 分P（标题带分P名） |
| 14 | 文件名只替换少量字符，超长标题、`CON` 之类保留名会让写文件失败 | 统一 `sanitize_filename`：控制符、保留名、长度、结尾点空格 |
| 15 | 抖音音频下载直接把视频地址存成 `.m4a`；B站合并时强制重编码音频 | 音频缺失时用 FFmpeg 提取音轨；合并默认直接复制音频流，失败再重编码 |
| 16 | `requirements.txt` 是 UTF-16 编码，且把整个虚拟环境的 50 多个无关包都当依赖 | 重写为 UTF-8，只保留 6 个真正用到的包 |
| 17 | 前端 `alert` 弹窗、按钮不置灰，重复点击会重复提交；SSE 断开无提示 | 改为 toast + 按钮禁用/加载态；连接状态提示，事件自动重连 |
| 18 | `msedgedriver.exe`（23 MB）随仓库分发 | 加入 `.gitignore`，改由 Selenium Manager 自动下载，缺失时才回退本地文件 |

---

## 🧪 开发与测试

测试不依赖网络和浏览器（下载测试使用本地 `http.server`），只用标准库即可运行：

```bash
python -m unittest discover -s tests -t . -v
```

装了 pytest 也可以直接跑（`unittest` 用例能被 pytest 收集）：

```bash
pip install -r requirements-dev.txt
python -m pytest
```

代码风格检查：

```bash
ruff check app tests web_app.py
```

> 本地还附了一份 GitHub Actions 配置（`.github/workflows/ci.yml`），推送到仓库即可启用自动化测试。注意：创建或更新 workflow 文件的令牌必须带 `workflow` 权限，否则 GitHub 会拒绝推送。

---

## ❓ 常见问题

**Q：B站解析出来只有 480P？**
未登录时 B站只下发低清晰度。请先「自动登录」或粘贴有效 Cookie；大会员内容还需要对应账号权限。

**Q：抖音解析一直超时？**
首次启动浏览器较慢，或触发了风控验证。请把 `DOUYIN_HEADLESS=0`（默认）保持可见窗口，手动过一次验证后再解析；也可以调大 `DOUYIN_API_TIMEOUT`。

**Q：提示找不到 Edge WebDriver？**
新版 Selenium 会自动下载驱动。若公司网络拦截，可手动下载与浏览器版本一致的 `msedgedriver.exe` 放到项目根目录。

**Q：合并失败 / 提示找不到 FFmpeg？**
执行 `pip install --force-reinstall imageio-ffmpeg` 重新安装内置二进制。

**Q：端口被占用？**
设置 `FLASK_PORT=5050` 后重启，或关闭占用 5000 端口的程序。

**Q：下载目录想换到 D 盘？**
在页面里点「浏览」选择目录，或设置 `DOWNLOAD_DIR=D:\videos`。

**Q：安全吗？**
服务默认只监听 `127.0.0.1`，不对外网开放；`/api/reveal` 只允许打开本程序自己下载的文件。请勿把 `FLASK_HOST` 改成 `0.0.0.0` 暴露到公网。

---

## 📄 许可证

[MIT](LICENSE) © 2026 yuanjian5653

如果这个项目对你有帮助，欢迎点个 ⭐。
