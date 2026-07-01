"""聊天 API: /api/chat, /api/chat/stream"""
import json
import os

from flask import Blueprint, request, jsonify, Response

from config import get_config
from logger import get_logger

log = get_logger(__name__)
chat_bp = Blueprint("chat", __name__)


# ─── 系统提示词 ──────────────────────────────────────────

SYSTEM_PROMPT_NO_CONTEXT = """\
# 角色定义

你是 BiliBrain 的 AI 知识助手，专门帮助用户分析、讨论和整理信息。

# 核心原则

1. **诚实透明**：如果问题需要具体上下文而你没有被告知，请如实说明
2. **结构化输出**：使用清晰的标题和列表组织回答
3. **中文优先**：始终使用中文回答，专有名词可保留英文
4. **拒绝越界**：对于与知识分析无关的请求，礼貌拒绝并引导用户回到正轨
"""

SYSTEM_PROMPT_WITH_CONTEXT = """\
# 角色定义

你是 BiliBrain 的 AI 知识助手，专门帮助用户分析和理解 B站视频内容。
你的职责是对捕获的网页/视频内容进行深度分析、总结、讨论和知识沉淀。

# 核心原则

1. **忠于原文**：所有分析必须基于提供的上下文内容。不要编造、推测或添加原文中不存在的信息。
2. **标注来源**：引用具体数据或观点时，尽量指明在原文中的位置或上下文。
3. **承认局限**：如果上下文中没有足够信息回答用户问题，明确说明"根据提供的材料，无法确定..."，不要强行作答。
4. **结构化输出**：使用清晰的标题、列表和段落组织回答，便于阅读和存档。
5. **中文优先**：始终使用中文回答，专有名词可保留英文。

# 输出规范

- 总结类问题：先给一句话概括（不超过 100 字），再展开要点
- 分析类问题：用逻辑层次结构（观点 -> 论据 -> 例证）
- 讨论类问题：多角度分析，明确指出不同立场的优劣
- 数据提取：用表格或列表呈现，标注每个数据的上下文来源

# 行为约束

- 如果用户问题与上下文无关，礼貌地引导用户回到内容讨论
- 不扮演"全能 AI"，不要说"我可以帮你做任何事"
- 回答长度适中：简单问题简短回复，复杂分析可以详细展开
- 避免使用"此外""值得注意的是""总而言之"等模板化过渡词

# 当前分析材料

以下是用户捕获的网页内容，你的分析必须基于这些材料：

---
{context}
---
"""


def _build_messages(message: str, context: str = "") -> list:
    """构建聊天消息列表"""
    if context:
        system_msg = SYSTEM_PROMPT_WITH_CONTEXT.replace("{context}", context[:8000])
    else:
        system_msg = SYSTEM_PROMPT_NO_CONTEXT
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": message},
    ]


@chat_bp.route("/api/chat", methods=["POST"])
def api_chat():
    """非流式聊天 (兼容旧版)"""
    data = request.get_json()
    message = data.get("message", "")
    context = data.get("context", "")
    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    from openai import OpenAI
    cfg = get_config()
    # OpenAI SDK 需要的是 https://api.deepseek.com 而非 /anthropic 端点
    base_url = cfg.anthropic_base_url
    if base_url.endswith("/anthropic"):
        base_url = base_url[:-len("/anthropic")]
    # 去掉模型名中的上下文窗口后缀 (如 [1m]), DeepSeek API 不认
    import re
    model = re.sub(r'\[\d+m\]$', '', cfg.anthropic_model)
    client = OpenAI(
        api_key=cfg.anthropic_auth_token,
        base_url=base_url,
    )
    messages = _build_messages(message, context)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=2048,
        )
        return jsonify({"reply": resp.choices[0].message.content})
    except Exception as e:
        log.error(f"AI 聊天错误: {e}")
        return jsonify({"error": f"AI 错误: {str(e)}"}), 500


@chat_bp.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    """流式聊天 (SSE)"""
    data = request.get_json()
    message = data.get("message", "")
    context = data.get("context", "")
    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    from openai import OpenAI
    cfg = get_config()
    base_url = cfg.anthropic_base_url
    if base_url.endswith("/anthropic"):
        base_url = base_url[:-len("/anthropic")]
    # 去掉模型名中的上下文窗口后缀 (如 [1m]), DeepSeek API 不认
    import re
    model = re.sub(r'\[\d+m\]$', '', cfg.anthropic_model)
    client = OpenAI(
        api_key=cfg.anthropic_auth_token,
        base_url=base_url,
    )
    messages = _build_messages(message, context)

    def generate():
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=2048,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'text': delta.content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            log.error(f"AI 流式错误: {e}")
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
