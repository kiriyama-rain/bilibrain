"""Flask Blueprint 注册 (BiliBrain 部署版 — 仅 B站 捕获)"""
from flask import Flask


def register_routes(app: Flask):
    """注册所有 API Blueprint"""
    from .tabs import tabs_bp
    from .capture import capture_bp
    from .chat import chat_bp
    from .save import save_bp
    app.register_blueprint(tabs_bp)
    app.register_blueprint(capture_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(save_bp)
