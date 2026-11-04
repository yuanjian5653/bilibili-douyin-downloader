"""Flask 应用工厂。"""

from __future__ import annotations

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .config import APP_NAME, DOWNLOAD_DIR, VERSION
from .routes import bp


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.json.sort_keys = False
    app.config["APP_NAME"] = APP_NAME
    app.config["VERSION"] = VERSION

    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[app] 无法创建下载目录 {DOWNLOAD_DIR}：{exc}")

    app.register_blueprint(bp)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "msg": exc.description}), exc.code
        return exc.get_response()

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):  # pragma: no cover - 兜底
        app.logger.exception("未处理异常：%s", exc)
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "msg": f"服务器内部错误：{exc}"}), 500
        return "服务器内部错误", 500

    @app.after_request
    def add_headers(response):
        if request.path.startswith("/api/"):
            # SSE 响应自己带了 Cache-Control，不要覆盖
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    return app
