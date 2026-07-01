"""
BiliBrain — Flask 后端入口 (部署版)
=====================================
纯 Extension 模式, 无 CDP 依赖。
前端由 Chrome Extension + static/ Web UI 提供。

启动: python app.py
      python app.py --port 5577
"""
import argparse
import threading
import time
from pathlib import Path

from flask import Flask, jsonify

from config import load_config, set_config
from logger import setup_logging, get_logger

APP_DIR = Path(__file__).parent

# ─── 配置 & 日志 ──────────────────────────────────────────
cfg = load_config()
set_config(cfg)
log = setup_logging(cfg.log_level, cfg.log_file)

# ─── Flask 应用 ──────────────────────────────────────────
app = Flask(
    __name__,
    static_folder=str(APP_DIR / "static"),
    static_url_path="",
)

from routes import register_routes
register_routes(app)


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """安全关闭 Flask 服务器"""
    import os, signal
    log.info("收到关闭请求, 正在停止服务...")

    def shutdown():
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=shutdown, daemon=True).start()
    return jsonify({"message": "服务端正在关闭..."})


# ─── 启动辅助 ────────────────────────────────────────────

def start_flask(port: int = None):
    import logging as _logging
    _logging.getLogger("werkzeug").setLevel(_logging.ERROR)
    app.run(host=cfg.flask_host, port=port or cfg.flask_port, debug=False)


def wait_for_flask(port: int = None, timeout: float = 5.0):
    import urllib.request
    p = port or cfg.flask_port
    for _ in range(int(timeout * 2)):
        try:
            urllib.request.urlopen(f"http://{cfg.flask_host}:{p}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


# ─── 主入口 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BiliBrain Server")
    parser.add_argument("--port", type=int, default=None, help="Flask 端口")
    args = parser.parse_args()

    flask_port = args.port or cfg.flask_port

    log.info("启动 Flask 服务器...")
    threading.Thread(target=start_flask, args=(flask_port,), daemon=True).start()
    if not wait_for_flask(flask_port):
        log.error("Flask 启动失败")
        return

    flask_url = f"http://{cfg.flask_host}:{flask_port}"
    log.info(f"Flask: {flask_url}")
    print(f"\n  BiliBrain 服务端已启动")
    print(f"  {flask_url}")
    print(f"  按 Ctrl+C 退出\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    log.info("服务端已关闭")


if __name__ == "__main__":
    main()
