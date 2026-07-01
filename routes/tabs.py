"""标签页 API: /api/status (部署版 — 无 CDP 依赖)"""
from flask import Blueprint, jsonify

tabs_bp = Blueprint("tabs", __name__)


@tabs_bp.route("/api/status")
def api_status():
    # Extension 模式下, 标签页由 Chrome Extension 直接管理
    return jsonify({
        "flask": "ok",
        "status": "ok",
        "mode": "extension-only",
    })


@tabs_bp.route("/api/tabs")
def api_tabs():
    return jsonify({"tabs": [], "note": "标签页列表由 Chrome Extension 提供"})


@tabs_bp.route("/api/activate", methods=["POST"])
def api_activate():
    return jsonify({"error": "CDP 模式未启用 (使用 Chrome Extension)"}), 400
