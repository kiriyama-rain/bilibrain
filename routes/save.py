"""保存 API: /api/save"""
from flask import Blueprint, request, jsonify

from brain_writer import save_capture

save_bp = Blueprint("save", __name__)


@save_bp.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json()
    result = save_capture(
        url=data.get("url", ""),
        title=data.get("title", "未命名"),
        markdown=data.get("markdown", ""),
        metadata=data.get("metadata"),
        with_wiki=data.get("with_wiki", False),
        summary=data.get("summary", ""),
        tags=data.get("tags", []),
    )
    return jsonify(result)
