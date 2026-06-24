"""
抽象处理器基类
==============
所有内容处理器的统一接口。

Phase 2 MultiModalProcessor 继承此类, 实现:
  1. 下载视频/音频
  2. 调用本地千问多模态模型
  3. 返回结构化分析结果
  4. 再通过 DeepSeek API 做讨论/总结
"""
from abc import ABC, abstractmethod


class BaseProcessor(ABC):
    """内容处理器抽象基类"""

    processor_name: str = "base"

    @abstractmethod
    def process(
        self,
        url: str = '',
        title: str = '',
        body_html: str = '',
        body_text: str = '',
        metadata: dict = None,
        **kwargs,
    ) -> dict:
        """
        处理内容, 返回统一格式:
        {
            "content_type": "webpage" | "video" | "audio",
            "markdown": str,
            "plain_text": str,
            "metadata": dict,
            "media_analysis": dict | None,    # Phase 2: 多模态分析结果
            "processor_used": str,
        }
        """
        ...
