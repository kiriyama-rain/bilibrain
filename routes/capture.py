"""
捕获 API: /api/capture, /api/last-capture, /api/captures
==========================================================
Extension 模式: 接收 body_html/body_text → content_cleaner → 存储 + 返回
无 CDP 依赖, 纯 Extension 驱动。
"""
from flask import Blueprint, request, jsonify

from logger import get_logger

log = get_logger(__name__)
capture_bp = Blueprint("capture", __name__)

# ─── 服务端捕获存储 ──────────────────────────────────────
_last_capture = None  # 最近一次捕获结果 (服务端内存)

# ─── 持久化辅助 ──────────────────────────────────────────

def _persist_capture(url, title, markdown, plain_text, content_type, metadata, captured_via, result):
    """将捕获结果写入 SQLite, 失败不影响捕获流程"""
    try:
        from capture_store import save_capture
        capture_id = save_capture(
            url=url,
            title=title,
            markdown=markdown,
            plain_text=plain_text,
            content_type=content_type,
            metadata=metadata,
            captured_via=captured_via,
        )
        result["id"] = capture_id
        global _last_capture
        if _last_capture:
            _last_capture["id"] = capture_id
        return capture_id
    except Exception as e:
        log.error(f"持久化失败 (不影响捕获结果): {e}")
        return None


@capture_bp.route("/api/last-capture")
def api_last_capture():
    """获取最近一次捕获结果 (供 Web UI 使用)"""
    global _last_capture
    if _last_capture:
        return jsonify(_last_capture)
    return jsonify({"error": "暂无捕获内容"}), 404


@capture_bp.route("/api/capture", methods=["POST"])
def api_capture():
    data = request.get_json()
    if data is None:
        return jsonify({"error": "请求体不能为空"}), 400

    if not data.get("body_html") and not data.get("body_text"):
        return jsonify({"error": "缺少 body_html 或 body_text"}), 400

    return _capture_from_extension(data)


def _capture_from_extension(data: dict):
    """处理来自 Chrome Extension 的内容"""
    url = data.get("url", "")
    title = data.get("title", "")
    body_html = data.get("body_html", "")
    body_text = data.get("body_text", "")
    metadata = data.get("metadata")
    content_type = data.get("content_type", "webpage")

    log.info(f"Extension 捕获: {title[:60]} (type={content_type})")

    try:
        if body_html:
            from content_cleaner import process_content
            cleaned = process_content(body_html)
            markdown = cleaned.get("markdown", "")
            plain_text = cleaned.get("plain_text", "")
        elif body_text:
            markdown = body_text
            plain_text = body_text
        else:
            return jsonify({"error": "没有可处理的内容"}), 400

        result = {
            "content_type": content_type,
            "markdown": markdown,
            "plain_text": plain_text,
            "text_length": len(plain_text),
            "title": title,
            "url": url,
            "metadata": metadata or {},
            "media_analysis": None,
            "captured_via": "extension",
        }
        # 存入服务端内存, 供 Web UI 拉取
        global _last_capture
        _last_capture = result
        # 持久化到 SQLite (失败不影响捕获结果)
        _persist_capture(
            url=url, title=title,
            markdown=markdown, plain_text=plain_text,
            content_type=content_type, metadata=metadata,
            captured_via="extension", result=result,
        )
        return jsonify(result)
    except Exception as e:
        log.exception("捕获处理失败")
        return jsonify({"error": f"处理失败: {e}"}), 500


# ─── 持久化历史查询 ──────────────────────────────────────

@capture_bp.route("/api/captures")
def api_list_captures():
    """列出最近的捕获记录 (仅返回预览, 不含完整内容)"""
    try:
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        limit = min(max(limit, 1), 200)
        offset = max(offset, 0)

        from capture_store import list_captures
        data = list_captures(limit=limit, offset=offset)
        return jsonify(data)
    except Exception as e:
        log.exception("获取捕获列表失败")
        return jsonify({"error": f"获取列表失败: {e}"}), 500


@capture_bp.route("/api/captures/<capture_id>")
def api_get_capture(capture_id: str):
    """获取单条捕获的完整内容"""
    try:
        from capture_store import get_capture as get_cap
        cap = get_cap(capture_id)
        if cap is None:
            return jsonify({"error": "捕获记录不存在"}), 404
        return jsonify(cap)
    except Exception as e:
        log.exception("获取捕获详情失败")
        return jsonify({"error": f"获取详情失败: {e}"}), 500


@capture_bp.route("/api/captures/<capture_id>", methods=["DELETE"])
def api_delete_capture(capture_id: str):
    """删除一条捕获记录"""
    try:
        from capture_store import delete_capture as del_cap
        deleted = del_cap(capture_id)
        if deleted:
            return jsonify({"deleted": True})
        return jsonify({"error": "捕获记录不存在"}), 404
    except Exception as e:
        log.exception("删除捕获失败")
        return jsonify({"error": f"删除失败: {e}"}), 500


# ─── 持久化历史查询 ──────────────────────────────────────

@capture_bp.route("/api/captures")
def api_list_captures():
    """列出最近的捕获记录 (仅返回预览, 不含完整内容)"""
    try:
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        limit = min(max(limit, 1), 200)  # 限制范围 1-200
        offset = max(offset, 0)

        from capture_store import list_captures
        data = list_captures(limit=limit, offset=offset)
        return jsonify(data)
    except Exception as e:
        log.exception("获取捕获列表失败")
        return jsonify({"error": f"获取列表失败: {e}"}), 500


@capture_bp.route("/api/captures/<capture_id>")
def api_get_capture(capture_id: str):
    """获取单条捕获的完整内容"""
    try:
        from capture_store import get_capture as get_cap
        cap = get_cap(capture_id)
        if cap is None:
            return jsonify({"error": "捕获记录不存在"}), 404
        return jsonify(cap)
    except Exception as e:
        log.exception("获取捕获详情失败")
        return jsonify({"error": f"获取详情失败: {e}"}), 500


@capture_bp.route("/api/captures/<capture_id>", methods=["DELETE"])
def api_delete_capture(capture_id: str):
    """删除一条捕获记录"""
    try:
        from capture_store import delete_capture as del_cap
        deleted = del_cap(capture_id)
        if deleted:
            return jsonify({"deleted": True})
        return jsonify({"error": "捕获记录不存在"}), 404
    except Exception as e:
        log.exception("删除捕获失败")
        return jsonify({"error": f"删除失败: {e}"}), 500
