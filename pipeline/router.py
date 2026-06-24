"""
内容类型路由器
==============
根据 content_type 和 URL 将内容路由到正确的处理器。

Phase 1: webpage → WebpageProcessor
Phase 2: video/audio → MultiModalProcessor → DeepSeek
"""
from logger import get_logger

log = get_logger(__name__)

# 视频平台域名 (与 content.js 保持一致)
VIDEO_DOMAINS = [
    'youtube.com', 'youtu.be', 'bilibili.com',
    'douyin.com', 'tiktok.com', 'iqiyi.com',
    'youku.com', 'v.qq.com', 'ixigua.com',
    'huya.com', 'douyu.com', 'kuaishou.com',
    'twitch.tv', 'vimeo.com',
]


def detect_content_type(url: str, content_type: str = None, media_meta: dict = None) -> str:
    """
    检测内容类型。
    优先级: 显式 content_type > URL 域名匹配 > 默认 webpage
    """
    if content_type and content_type != 'webpage':
        return content_type

    # URL 兜底检测
    host = (url or '').lower()
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ''
    except Exception:
        pass

    for domain in VIDEO_DOMAINS:
        if domain in host:
            return 'video'

    return 'webpage'


def route_content(
    url: str,
    title: str = '',
    body_html: str = '',
    body_text: str = '',
    metadata: dict = None,
    content_type: str = None,
    media_meta: dict = None,
):
    """
    路由内容到合适的处理器。

    Phase 1: 所有内容走 WebpageProcessor
    Phase 2: video/audio 先走 MultiModalProcessor, 再走 WebpageProcessor 格式化为 Markdown

    返回: { content_type, markdown, plain_text, media_analysis (Phase 2), ... }
    """
    detected_type = detect_content_type(url, content_type, media_meta)

    if detected_type == 'video' or detected_type == 'audio':
        # Phase 2: 多模态处理
        log.info(f"多模态内容: {detected_type} — {url}")
        try:
            from .processors.multimodal import MultiModalProcessor
            processor = MultiModalProcessor()
            return processor.process(
                url=url, title=title,
                body_text=body_text, metadata=metadata,
                media_meta=media_meta, content_type=detected_type,
            )
        except ImportError:
            log.warning("MultiModalProcessor 不可用 (Phase 2), 回退到网页处理")
        except Exception as e:
            log.error(f"多模态处理失败: {e}, 回退到网页处理")

    # 默认: 网页处理
    from .processors.webpage import WebpageProcessor
    processor = WebpageProcessor()
    return processor.process(
        url=url, title=title,
        body_html=body_html, body_text=body_text,
        metadata=metadata,
    )
