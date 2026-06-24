"""
CDP 通信封装 — 标签页发现 / 内容捕获 / SPA 模态框检测
=====================================================
优化:
  - body.outerHTML 替代 documentElement (节省 ~30% 传输)
  - WebSocket 连接池 (消除每次捕获 ~500ms 建连开销)
  - 内容缓存 (30s TTL，避免重复捕获)
  - META_JS 元数据提取 (移植自 V1)
  - _connect_tab 重试 (指数退避 0.5s/1s/2s)
"""
import json
import time
import urllib.request
from urllib.parse import urlparse

from logger import get_logger

log = get_logger(__name__)

CHROME_PORT = 9222

# ─── WS 连接池 ─────────────────────────────────────────────────
_ws_pool: dict = {}      # {tab_id: (ws, last_used_ts)}
_ws_pool_max_idle = 60   # 60s 空闲自动关闭
_capture_cache: dict = {}  # {tab_id: (timestamp, result)}
_cache_ttl = 30           # 30s TTL


def _get_ws(tab_id: str):
    """从连接池获取或创建 WebSocket，返回 (ws, error)"""
    import websocket

    entry = _ws_pool.get(tab_id)
    if entry:
        ws, _ = entry
        try:
            ws.ping()
            _ws_pool[tab_id] = (ws, time.time())
            return ws, None
        except Exception:
            log.debug(f"Tab {tab_id}: 池中连接已断，移除")
            del _ws_pool[tab_id]

    return _connect_tab(tab_id)


def _cleanup_ws_pool():
    """关闭空闲连接"""
    now = time.time()
    stale = [
        tid for tid, (_, last) in _ws_pool.items()
        if now - last > _ws_pool_max_idle
    ]
    for tid in stale:
        try:
            _ws_pool[tid][0].close()
        except Exception:
            pass
        del _ws_pool[tid]
    if stale:
        log.debug(f"WS 池清理: 关闭 {len(stale)} 个空闲连接")


def _invalidate_cache_for_tab(tab_id: str):
    """使指定标签页的缓存失效"""
    _capture_cache.pop(tab_id, None)


# ─── 标签页列表 ───────────────────────────────────────────────


def get_tabs() -> list[dict]:
    """通过 HTTP /json 获取所有标签页，排除内部页面"""
    try:
        req = urllib.request.urlopen(
            f"http://localhost:{CHROME_PORT}/json", timeout=1
        )
        all_tabs = json.loads(req.read())
        result = []
        for tab in all_tabs:
            url = tab.get("url", "")
            if url.startswith("chrome://") or url.startswith("devtools://"):
                continue
            if url == "about:blank" or not url:
                continue
            result.append({
                "id": tab.get("id"),
                "title": tab.get("title", "无标题"),
                "url": url,
                "favicon": tab.get("faviconUrl", ""),
                "type": tab.get("type", "page"),
            })
        return result
    except Exception:
        return []


def activate_tab(tab_id: str) -> bool:
    """通过 HTTP 激活指定标签页"""
    try:
        req = urllib.request.urlopen(
            f"http://localhost:{CHROME_PORT}/json/activate/{tab_id}",
            timeout=5,
        )
        return req.status == 200
    except Exception:
        return False


# ─── WebSocket 通信 ────────────────────────────────────────────


def _send_cmd(ws, cmd_id: int, method: str, params: dict = None) -> dict:
    """发送 CDP 命令并等待响应"""
    msg = {"id": cmd_id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == cmd_id:
            return resp


def _connect_tab(tab_id: str, retry_attempts: int = 3):
    """
    建立到指定标签页的 WebSocket 连接，返回 (ws, error)。
    失败时按指数退避重试。
    """
    import websocket

    backoffs = (0.5, 1.0, 2.0)
    last_error = None

    for attempt in range(retry_attempts):
        try:
            ws = websocket.create_connection(
                f"ws://localhost:{CHROME_PORT}/devtools/page/{tab_id}",
                timeout=5,
            )
            _send_cmd(ws, 1, "Page.enable")
            _send_cmd(ws, 2, "Runtime.enable")
            # 添加到连接池
            _ws_pool[tab_id] = (ws, time.time())
            return ws, None
        except Exception as e:
            last_error = str(e)
            if attempt < retry_attempts - 1:
                delay = backoffs[min(attempt, len(backoffs) - 1)]
                log.debug(
                    f"Tab {tab_id}: 连接失败 (尝试 {attempt+1}/{retry_attempts}), "
                    f"{delay}s 后重试"
                )
                time.sleep(delay)

    log.error(f"Tab {tab_id}: 连接失败，已达最大重试次数: {last_error}")
    return None, last_error


# ─── SPA 模态框检测 ────────────────────────────────────────────

MODAL_DETECT_JS = """
(function() {
    var selectors = [
        '[class*="modal"]', '[class*="overlay"]', '[class*="popup"]',
        '[class*="detail"]', '[class*="player"]', '[class*="layer"]',
        '[class*="dialog"]', '[class*="drawer"]', '[class*="panel"]',
        '[class*="sidebar"]', '[class*="preview"]',
        '.video-detail', '.video-player', '.video-modal',
        'div[style*="fixed"]', 'div[style*="absolute"]'
    ];
    var found = [];
    for (var s of selectors) {
        var els = document.querySelectorAll(s);
        for (var el of els) {
            try {
                var rect = el.getBoundingClientRect();
                var style = window.getComputedStyle(el);
                if (rect.width > 200 && rect.height > 100 &&
                    style.display !== 'none' && style.visibility !== 'hidden' &&
                    el.offsetParent !== null) {
                    found.push({
                        selector: s,
                        tag: el.tagName,
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                        z: style.zIndex,
                        text: (el.innerText || '').substring(0, 200)
                    });
                }
            } catch(e) {}
        }
    }
    found.sort(function(a, b) { return (parseInt(b.z) || 0) - (parseInt(a.z) || 0); });
    return JSON.stringify(found);
})();
"""


def detect_modal(ws) -> list:
    """检测页面中是否有可见的模态框/浮层，返回匹配列表"""
    try:
        result = _send_cmd(ws, 10, "Runtime.evaluate", {
            "expression": MODAL_DETECT_JS,
            "returnByValue": True,
        })
        val = result.get("result", {}).get("result", {}).get("value", "[]")
        if isinstance(val, str):
            return json.loads(val)
        return val
    except Exception:
        return []


EXTRACT_MODAL_JS = """
(function() {
    var selectors = [
        '[class*="modal"]', '[class*="overlay"]', '[class*="popup"]',
        '[class*="detail"]', '[class*="player"]', '[class*="layer"]',
        '[class*="dialog"]', '[class*="preview"]', '[class*="drawer"]',
        '.video-detail', '.video-player', '.video-modal',
        'div[style*="fixed"]', 'div[style*="absolute"]',
        '[class*="video-detail"]', '[class*="video-info"]',
        '[class*="author"]', '[class*="desc"]',
    ];
    var best = null, bestArea = 0;
    for (var s of selectors) {
        var els = document.querySelectorAll(s);
        for (var el of els) {
            try {
                var rect = el.getBoundingClientRect();
                var style = window.getComputedStyle(el);
                if (rect.width > 200 && rect.height > 100 &&
                    style.display !== 'none' && style.visibility !== 'hidden' &&
                    el.offsetParent !== null &&
                    !el.closest('header') && !el.closest('nav') && !el.closest('footer')) {
                    var area = rect.width * rect.height;
                    if (area > bestArea) {
                        bestArea = area;
                        best = el;
                    }
                }
            } catch(e) {}
        }
    }
    if (best) {
        var textParts = [];
        var textEls = best.querySelectorAll('p, span, h1, h2, h3, h4, h5, h6, div, section');
        for (var el of textEls) {
            try {
                var text = (el.innerText || '').trim();
                if (text.length < 5) continue;
                if (el.tagName === 'BUTTON') continue;
                var tag = el.tagName.toLowerCase();
                var cls = (el.className || '') + ' ' + (el.id || '');
                if (/btn|button|control|slider|progress|timeline|seek|play|pause|time/i.test(cls)) continue;
                if (/^\\d+:\\d+/.test(text)) continue;
                if (text.replace(/[\\s\\d]/g, '').length < 3) continue;
                var parent = el.parentElement;
                if (parent && (parent.innerText || '').trim() === text && parent !== best) continue;
                textParts.push(text);
            } catch(e) {}
        }
        var unique = [];
        var seen = new Set();
        for (var t of textParts) {
            var key = t.substring(0, 50);
            if (!seen.has(key)) { seen.add(key); unique.push(t); }
        }
        var fullText = unique.join('\\n');

        var clone = best.cloneNode(true);
        clone.querySelectorAll('script, style, noscript, iframe, button, svg, ' +
            '[class*="btn"], [class*="control"], [class*="slider"], [class*="progress"]').forEach(function(e) { e.remove(); });

        return JSON.stringify({
            found: true,
            text: fullText.substring(0, 50000),
            html: clone.innerHTML.substring(0, 200000)
        });
    }
    return JSON.stringify({found: false});
})();
"""


# ─── 页面内容提取 ──────────────────────────────────────────────

EXTRACT_ARTICLE_JS = """
(function() {
    var article = document.querySelector('article');
    if (article) return article.innerText.substring(0, 100000);
    var main = document.querySelector('main');
    if (main) return main.innerText.substring(0, 100000);
    var candidates = document.querySelectorAll('div, section, p');
    var best = '', bestLen = 0;
    for (var el of candidates) {
        var text = el.innerText || '';
        if (text.length > bestLen) { bestLen = text.length; best = text; }
    }
    if (bestLen > 200) return best.substring(0, 100000);
    return document.body.innerText.substring(0, 100000);
})();
"""

# 优化: 使用 body.outerHTML 替代 documentElement.outerHTML
# 节省 ~30% 传输量（排除 <head>），消除 JS 侧截断
EXTRACT_FULL_HTML_JS = """
(function() {
    var body = document.body.cloneNode(true);
    body.querySelectorAll('script, style, noscript, iframe, svg, template').forEach(function(e) { e.remove(); });
    return body.outerHTML;
})();
"""

# ─── 元数据提取 (移植自 V1 content_pipeline.py) ────────────────

META_JS = """
(function() {
    var get = function(sel, attr) {
        var el = document.querySelector(sel);
        return el ? (el.getAttribute(attr) || el.content || el.textContent || '') : '';
    };
    return JSON.stringify({
        ogTitle: get('meta[property="og:title"]', 'content'),
        author: get('meta[name="author"]', 'content')
            || get('meta[property="article:author"]', 'content')
            || '',
        published: get('meta[property="article:published_time"]', 'content')
            || get('meta[name="date"]', 'content')
            || '',
        description: get('meta[name="description"]', 'content')
            || get('meta[property="og:description"]', 'content')
            || '',
        siteName: get('meta[property="og:site_name"]', 'content')
            || get('meta[name="application-name"]', 'content')
            || '',
        keywords: get('meta[name="keywords"]', 'content')
            || '',
        ogImage: get('meta[property="og:image"]', 'content')
            || ''
    });
})();
"""


def _extract_metadata(ws) -> dict:
    """通过 CDP 提取页面元数据 (OG 标签、作者、日期等)"""
    try:
        result = _send_cmd(ws, 15, "Runtime.evaluate", {
            "expression": META_JS,
            "returnByValue": True,
        })
        val = result.get("result", {}).get("result", {}).get("value", "{}")
        if isinstance(val, str):
            return json.loads(val)
        return val if val else {}
    except Exception as e:
        log.debug(f"元数据提取失败: {e}")
        return {}


# ─── 一级捕获接口 ──────────────────────────────────────────────


def capture_tab(tab_id: str, use_cache: bool = True,
                use_pool: bool = True) -> dict:
    """捕获指定标签页的内容，自动检测模态框"""
    result = {"tab_id": tab_id, "has_modal": False}

    # ── 缓存检查 ──────────────────────────────
    if use_cache:
        cached = _capture_cache.get(tab_id)
        if cached:
            ts, data = cached
            if time.time() - ts < _cache_ttl:
                data["_from_cache"] = True
                log.debug(f"Tab {tab_id}: 缓存命中")
                return {**data}

    # ── 获取连接 ──────────────────────────────
    if use_pool:
        ws, error = _get_ws(tab_id)
    else:
        ws, error = _connect_tab(tab_id, retry_attempts=1)

    if error:
        result["error"] = f"连接失败: {error}"
        return result

    try:
        # 获取页面基本信息
        info = _send_cmd(ws, 20, "Runtime.evaluate", {
            "expression": "JSON.stringify({title:document.title,url:location.href})",
            "returnByValue": True,
        })
        page_info_val = info.get("result", {}).get("result", {}).get("value", "{}")
        if isinstance(page_info_val, str):
            page_info = json.loads(page_info_val)
        else:
            page_info = page_info_val if page_info_val else {}
        result["title"] = page_info.get("title", "")
        result["url"] = page_info.get("url", "")

        # 提取元数据 (移植自 V1)
        metadata = _extract_metadata(ws)
        if metadata:
            result["metadata"] = metadata
            # 用 OG 标题回退
            if not result["title"] and metadata.get("ogTitle"):
                result["title"] = metadata["ogTitle"]
            result["author"] = metadata.get("author", "")
            result["published"] = metadata.get("published", "")
            result["description"] = metadata.get("description", "")
            result["keywords"] = metadata.get("keywords", "")
            result["site_name"] = metadata.get("siteName", "")

        # 检测模态框
        modals = detect_modal(ws)
        if modals:
            result["has_modal"] = True
            result["modals_found"] = len(modals)
            result["modal_hint"] = modals[0].get("text", "")[:200] if modals else ""

            # 提取模态框内容
            modal_data = _send_cmd(ws, 30, "Runtime.evaluate", {
                "expression": EXTRACT_MODAL_JS,
                "returnByValue": True,
            })
            modal_val = modal_data.get("result", {}).get("result", {}).get("value", "{}")
            if isinstance(modal_val, str):
                modal_info = json.loads(modal_val)
            else:
                modal_info = modal_val if modal_val else {}
            if modal_info.get("found"):
                result["modal_content"] = modal_info.get("text", "")
                result["extracted_from"] = "modal"
                result["modal_html"] = modal_info.get("html", "")
        else:
            result["extracted_from"] = "article"
            # 没有模态框，提取页面正文 (body.outerHTML)
            article_data = _send_cmd(ws, 30, "Runtime.evaluate", {
                "expression": EXTRACT_FULL_HTML_JS,
                "returnByValue": True,
            })
            article_html = article_data.get("result", {}).get("result", {}).get("value", "")
            result["page_html"] = article_html
            result["raw_text_length"] = len(article_html)

    except Exception as e:
        result["error"] = f"捕获失败: {str(e)}"
        # 即使出错也返回已获取的部分信息
        log.warning(f"Tab {tab_id}: 捕获异常 (已返回部分结果): {e}")
        # 异常时使连接池中的连接失效
        _ws_pool.pop(tab_id, None)

    # 注意: 使用连接池时不关闭 WebSocket
    if not use_pool and 'ws' in dir():
        try:
            ws.close()
        except Exception:
            pass

    result["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    # 存入缓存
    _capture_cache[tab_id] = (time.time(), result)

    # 定期清理空闲连接
    _cleanup_ws_pool()

    return result


def capture_with_text(tab_id: str) -> dict:
    """捕获并追加纯文本（兼容模式）"""
    result = capture_tab(tab_id)
    if "error" in result:
        return result

    if result.get("modal_content"):
        result["text"] = result["modal_content"]
    elif result.get("page_html"):
        result["text"] = ""
    else:
        result["text"] = ""

    return result
