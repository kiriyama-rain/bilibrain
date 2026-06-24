"""
网页处理器
==========
Phase 1: HTML 清洗 → Markdown 转换
"""
from content_cleaner import process_content

from .base import BaseProcessor


class WebpageProcessor(BaseProcessor):
    processor_name = "webpage"

    def process(
        self,
        url: str = '',
        title: str = '',
        body_html: str = '',
        body_text: str = '',
        metadata: dict = None,
        **kwargs,
    ) -> dict:

        if body_html:
            cleaned = process_content(body_html)
            markdown = cleaned.get("markdown", "")
            plain_text = cleaned.get("plain_text", "")
        elif body_text:
            markdown = body_text
            plain_text = body_text
        else:
            markdown = ""
            plain_text = ""

        return {
            "content_type": "webpage",
            "markdown": markdown,
            "plain_text": plain_text,
            "text_length": len(plain_text),
            "title": title,
            "url": url,
            "metadata": metadata or {},
            "media_analysis": None,
            "processor_used": self.processor_name,
        }
