"""标签页 API: /api/status, /api/tabs, /api/activate"""
from flask import Blueprint, jsonify

from cdp_handler import get_tabs, activate_tab

tabs_bp = Blueprint("tabs", __name__)


@tabs_bp.route("/api/status")
def api_status():
    # Extension 模式下, Chrome 连接由扩展的 chrome.tabs API 保证
    # CDP 只是可选的 fallback, 不影响核心功能
    cdp_tabs = get_tabs()
    return jsonify({
        "cdp_connected": len(cdp_tabs) > 0,
        "cdp_tab_count": len(cdp_tabs),
        "flask": "ok",
        "status": "ok",
    })


@tabs_bp.route("/api/tabs")
def api_tabs():
    return jsonify({"tabs": get_tabs()})


@tabs_bp.route("/api/activate", methods=["POST"])
def api_activate():
    from flask import request
    data = request.get_json()
    tab_id = data.get("tab_id")
    if not tab_id:
        return jsonify({"error": "缺少 tab_id"}), 400
    return jsonify({"success": activate_tab(tab_id)})
