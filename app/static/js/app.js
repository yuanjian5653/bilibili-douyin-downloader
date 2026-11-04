/* 双平台视频下载器 —— 前端交互脚本 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const PLATFORM_BUTTONS = {
    bili: ["bili-login-btn", "bili-clear-btn", "bili-cookie-btn", "bili-parse-btn", "bili-download-btn"],
    douyin: ["douyin-parse-btn", "douyin-download-btn"],
  };

  const app = {
    busy: { bili: false, douyin: false },
    parsed: { bili: false, douyin: false },
    lastPath: { bili: "", douyin: "" },
  };

  /* ===================== 通用工具 ===================== */
  function fmtBytes(bytes) {
    if (!bytes || bytes < 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = bytes;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return (index === 0 ? Math.round(value) : value.toFixed(1)) + " " + units[index];
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function toast(message, kind) {
    const wrap = $("toast-wrap");
    if (!wrap) return;
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = message;
    wrap.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transform = "translateY(6px)";
      setTimeout(() => el.remove(), 200);
    }, 3600);
  }

  async function post(url, payload) {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
      });
      let data = {};
      try {
        data = await response.json();
      } catch (err) {
        data = { ok: false, msg: "服务器返回了非 JSON 响应" };
      }
      if (!response.ok && data.ok !== false) {
        data.ok = false;
        data.msg = data.msg || "请求失败（HTTP " + response.status + "）";
      }
      return data;
    } catch (err) {
      return { ok: false, msg: "网络请求失败：" + err };
    }
  }

  /* ===================== 标签页 ===================== */
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((item) => {
        item.classList.remove("active");
        item.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".panel").forEach((panel) => panel.classList.remove("active"));
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      const panel = $("panel-" + tab.dataset.tab);
      if (panel) panel.classList.add("active");
    });
  });

  /* ===================== 按钮状态 ===================== */
  function setBusy(platform, busy) {
    app.busy[platform] = busy;
    PLATFORM_BUTTONS[platform].forEach((id) => {
      const button = $(id);
      if (!button) return;
      button.classList.remove("busy");
      if (busy) {
        button.disabled = true;
      } else {
        // 下载按钮在解析成功前保持禁用
        button.disabled = id === platform + "-download-btn" && !app.parsed[platform];
      }
    });
  }

  function markBusy(platform, buttonId) {
    setBusy(platform, true);
    const button = $(buttonId);
    if (button) button.classList.add("busy");
  }

  /* ===================== 日志 & 进度 ===================== */
  function appendLog(platform, message, level) {
    const box = $(platform + "-log");
    if (!box) return;
    const line = document.createElement("div");
    line.className = "log-line" + (level ? " level-" + level : "");
    const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    line.innerHTML = '<span class="time">' + time + "</span>" + escapeHtml(message);
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
    while (box.childElementCount > 400) box.removeChild(box.firstElementChild);
  }

  function setProgress(platform, data) {
    const bar = $(platform + "-progress");
    const text = $(platform + "-progress-text");
    const value = typeof data.value === "number" ? data.value : 0;
    if (bar) bar.style.width = Math.max(0, Math.min(100, value)) + "%";
    if (!text) return;
    let label;
    if (data.total) {
      label = value.toFixed(0) + "% · " + fmtBytes(data.downloaded) + " / " + fmtBytes(data.total);
    } else if (data.downloaded) {
      label = fmtBytes(data.downloaded) + " 已下载";
    } else if (value > 0) {
      label = value.toFixed(0) + "%";
    } else {
      label = "准备中...";
    }
    text.textContent = label;
  }

  function resetProgress(platform) {
    const bar = $(platform + "-progress");
    if (bar) bar.style.width = "0%";
    const text = $(platform + "-progress-text");
    if (text) text.textContent = "任务进行中...";
    const result = $(platform + "-result");
    if (result) result.hidden = true;
  }

  function showResult(platform, path, size) {
    app.lastPath[platform] = path;
    const wrap = $(platform + "-result");
    const label = $(platform + "-result-path");
    if (wrap) wrap.hidden = false;
    if (label) label.textContent = path + (size ? "（" + size + "）" : "");
    const bar = $(platform + "-progress");
    if (bar) bar.style.width = "100%";
    const text = $(platform + "-progress-text");
    if (text) text.textContent = "下载完成" + (size ? " · " + size : "");
  }

  /* ===================== SSE ===================== */
  function setConnection(online) {
    const el = $("conn-status");
    if (!el) return;
    el.textContent = online ? "日志已连接" : "连接断开，正在重连...";
    el.className = "conn " + (online ? "online" : "offline");
  }

  function connectSSE(platform) {
    const source = new EventSource("/api/stream/" + platform);
    source.onopen = () => setConnection(true);
    source.onerror = () => setConnection(false);
    source.onmessage = (event) => {
      if (!event.data) return;
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      switch (data.type) {
        case "hello":
          setConnection(true);
          break;
        case "log":
          appendLog(platform, data.msg, data.level);
          break;
        case "progress":
          setProgress(platform, data);
          break;
        case "done":
          setBusy(platform, false);
          showResult(platform, data.path, data.size);
          toast("下载完成：" + data.path, "ok");
          break;
        case "error":
          setBusy(platform, false);
          toast(data.msg || "操作失败", "error");
          break;
        case "bili_parsed":
          onBiliParsed(data);
          break;
        case "douyin_parsed":
          onDouyinParsed(data);
          break;
        case "login_status":
          updateLoginStatus(data.value);
          setBusy("bili", false);
          toast(data.value ? "B站登录成功" : "B站登录未完成", data.value ? "ok" : "error");
          break;
        default:
          break;
      }
    };
  }

  /* ===================== B站 ===================== */
  function updateLoginStatus(ok) {
    const el = $("bili-status");
    if (!el) return;
    el.textContent = ok ? "已登录" : "未登录或已失效";
    el.className = ok ? "status-ok" : "status-bad";
  }

  async function checkBiliStatus() {
    try {
      const response = await fetch("/api/bili/status");
      const data = await response.json();
      updateLoginStatus(Boolean(data.logged_in));
    } catch (err) {
      updateLoginStatus(false);
    }
  }

  async function biliLogin() {
    markBusy("bili", "bili-login-btn");
    appendLog("bili", "正在启动 Edge 浏览器，请在窗口中完成登录 ...");
    const result = await post("/api/bili/login");
    if (!result.ok) {
      setBusy("bili", false);
      toast(result.msg || "无法启动登录", "error");
    }
  }

  async function biliClear() {
    const result = await post("/api/bili/clear");
    if (result.ok) {
      updateLoginStatus(false);
      toast("已清除 Cookie", "ok");
    } else {
      toast(result.msg || "清除失败", "error");
    }
  }

  async function biliSaveCookie() {
    const input = $("bili-cookie-input");
    const cookie = input ? input.value.trim() : "";
    if (!cookie) return toast("请先粘贴 Cookie", "error");
    markBusy("bili", "bili-cookie-btn");
    const result = await post("/api/bili/cookie", { cookie });
    setBusy("bili", false);
    if (result.ok) {
      updateLoginStatus(true);
      if (input) input.value = "";
      toast("Cookie 保存成功", "ok");
    } else {
      toast(result.msg || "Cookie 校验失败", "error");
    }
  }

  async function biliParse() {
    const input = $("bili-url");
    const url = input ? input.value.trim() : "";
    if (!url) return toast("请输入视频链接", "error");
    app.parsed.bili = false;
    const title = $("bili-title");
    if (title) title.textContent = "视频标题：解析中...";
    resetProgress("bili");
    markBusy("bili", "bili-parse-btn");
    const result = await post("/api/bili/parse", { url });
    if (!result.ok) {
      setBusy("bili", false);
      if (title) title.textContent = "视频标题：尚未解析";
      toast(result.msg || "解析请求失败", "error");
    }
  }

  function onBiliParsed(data) {
    setBusy("bili", false);
    const title = $("bili-title");
    const select = $("bili-quality");
    if (data.error) {
      app.parsed.bili = false;
      if (title) title.textContent = "视频标题：解析失败";
      if (select) select.innerHTML = "";
      toast(data.error, "error");
      return;
    }
    app.parsed.bili = true;
    if (title) title.textContent = "视频标题：" + data.title;
    if (select) {
      select.innerHTML = "";
      (data.qualities || []).forEach((label, index) => {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = label;
        select.appendChild(option);
      });
      const defaultIndex = typeof data.default_index === "number"
        ? data.default_index
        : select.options.length - 1;
      if (defaultIndex >= 0) select.selectedIndex = defaultIndex;
    }
    $("bili-download-btn").disabled = false;
    toast("解析成功：" + data.title, "ok");
  }

  async function biliDownload() {
    const modeInput = document.querySelector('input[name="bili-mode"]:checked');
    const select = $("bili-quality");
    const dir = $("bili-dir");
    resetProgress("bili");
    markBusy("bili", "bili-download-btn");
    const result = await post("/api/bili/download", {
      mode: modeInput ? modeInput.value : "full",
      quality_index: select ? select.selectedIndex : -1,
      save_dir: dir ? dir.value.trim() : "",
    });
    if (!result.ok) {
      setBusy("bili", false);
      toast(result.msg || "下载请求失败", "error");
    }
  }

  /* ===================== 抖音 ===================== */
  async function douyinParse() {
    const input = $("douyin-text");
    const text = input ? input.value.trim() : "";
    if (!text) return toast("请粘贴分享内容", "error");
    app.parsed.douyin = false;
    const title = $("douyin-title");
    if (title) title.textContent = "视频标题：解析中...";
    resetProgress("douyin");
    markBusy("douyin", "douyin-parse-btn");
    const result = await post("/api/douyin/parse", { text });
    if (!result.ok) {
      setBusy("douyin", false);
      if (title) title.textContent = "视频标题：尚未解析";
      toast(result.msg || "解析请求失败", "error");
    }
  }

  function onDouyinParsed(data) {
    setBusy("douyin", false);
    const title = $("douyin-title");
    if (data.error) {
      app.parsed.douyin = false;
      if (title) title.textContent = "视频标题：解析失败";
      toast(data.error, "error");
      return;
    }
    app.parsed.douyin = true;
    if (title) title.textContent = "视频标题：" + data.title;
    $("douyin-download-btn").disabled = false;
    toast("解析成功：" + data.title, "ok");
  }

  async function douyinDownload() {
    const modeInput = document.querySelector('input[name="douyin-mode"]:checked');
    const dir = $("douyin-dir");
    resetProgress("douyin");
    markBusy("douyin", "douyin-download-btn");
    const result = await post("/api/douyin/download", {
      mode: modeInput ? modeInput.value : "full",
      save_dir: dir ? dir.value.trim() : "",
    });
    if (!result.ok) {
      setBusy("douyin", false);
      toast(result.msg || "下载请求失败", "error");
    }
  }

  /* ===================== 本地目录 / 文件 ===================== */
  async function browseDir(inputId) {
    const result = await post("/api/browse");
    if (result.ok && result.dir) {
      const input = $(inputId);
      if (input) input.value = result.dir;
    } else if (!result.ok && result.msg) {
      toast(result.msg, "error");
    }
  }

  async function revealFile(platform) {
    const path = app.lastPath[platform];
    if (!path) return;
    const result = await post("/api/reveal", { path });
    if (!result.ok) toast(result.msg || "无法打开文件管理器", "error");
  }

  /* ===================== 初始化 ===================== */
  window.biliLogin = biliLogin;
  window.biliClear = biliClear;
  window.biliSaveCookie = biliSaveCookie;
  window.biliParse = biliParse;
  window.biliDownload = biliDownload;
  window.douyinParse = douyinParse;
  window.douyinDownload = douyinDownload;
  window.browseDir = browseDir;
  window.revealFile = revealFile;

  document.addEventListener("DOMContentLoaded", () => {
    connectSSE("bili");
    connectSSE("douyin");
    checkBiliStatus();
    setBusy("bili", false);
    setBusy("douyin", false);

    const urlInput = $("bili-url");
    if (urlInput) {
      urlInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") biliParse();
      });
    }
    const douyinText = $("douyin-text");
    if (douyinText) {
      douyinText.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) douyinParse();
      });
    }
  });
})();
