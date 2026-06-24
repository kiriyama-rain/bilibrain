"""Flask Blueprint 注册"""
from flask import Flask

from .tabs import tabs_bp
from .capture import capture_bp
from .chat import chat_bp
from .save import save_bp
from .transcribe import transcribe_bp


def register_routes(app: Flask):
    """注册所有 API Blueprint"""
    app.register_blueprint(tabs_bp)
    app.register_blueprint(capture_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(save_bp)
    app.register_blueprint(transcribe_bp)
