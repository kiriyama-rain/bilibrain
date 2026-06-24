"""
多模态处理器 — 视频/音频内容提取
=================================
流程: yt-dlp 提取字幕/元数据 -> Markdown 组装

约束: 不下载视频文件 (yt-dlp --skip-download)
"""
import json
import tempfile
import time
from pathlib import Path
from typing import Optional

from .base import BaseProcessor
from logger import get_logger

log = get_logger(__name__)


class MultiModalProcessor(BaseProcessor):
    processor_name = "multimodal"

    # ── 主入口 ──────────────────────────────────────────────

    def process(self, url='', title='', body_text='', metadata=None,
                media_meta=None, content_type='video', **kwargs) -> dict:
        """多模态处理主流程"""
        log.info("[Phase2] process: %s %s", content_type, url)

        result = {
            "content_type": content_type, "url": url,
            "title": title, "metadata": metadata or {},
            "media_meta": media_meta, "media_analysis": None,
            "processor_used": self.processor_name,
        }

        # Step 1: yt-dlp 提取字幕 (可选增强)
        sub_info = self._extract_subtitles(url)
        # 优先使用 extension content script 字幕 > yt-dlp > 元数据
        ext_meta = media_meta or {}
        vt = ext_meta.get("title") or (sub_info or {}).get("title") or title
        vd = ext_meta.get("desc") or (sub_info or {}).get("description") or ""
        vdur = ext_meta.get("duration") or (sub_info or {}).get("duration", 0)
        vup = ext_meta.get("author") or (sub_info or {}).get("uploader", "")
        # 字幕: extension content.js 直接提取的 > yt-dlp
        ext_subs = ext_meta.get("subtitle_text", "")
        yt_subs = (sub_info or {}).get("text", "")
        subs_text = ext_subs if len(ext_subs) > len(yt_subs) else yt_subs
        sub_lang = (sub_info or {}).get("language", "")
        has_subs = len(subs_text) > 50

        result.update({
            "subtitles": subs_text,
            "video_title": vt,
            "video_description": vd[:2000],
            "video_duration": vdur,
            "video_uploader": vup,
            "subtitle_lang": sub_lang,
            "has_subtitles": has_subs,
        })

        # Step 2: 字幕状态判断 (根据 extension 的 subtitle_status)
        sub_status = ext_meta.get("subtitle_status", "")
        subs_len = len(result.get("subtitles", ""))

        if subs_len >= 200:
            result["hard_embedded_subs"] = False
        elif sub_status == "api_success_no_subs":
            # API 调用成功但确实无软字幕 → 确定是硬字幕
            result["hard_embedded_subs"] = True
            result["subtitle_status"] = "hard_embedded"
            log.info("确认硬字幕: API 返回空字幕列表 (%d 字)", subs_len)
        elif sub_status == "api_failed":
            # API 调用失败 (CORS/认证等) → 可能仍有 AI 字幕, 不能确定
            result["hard_embedded_subs"] = False
            result["subtitle_status"] = "api_failed"
            log.info("字幕 API 调用失败, 无法判断是否有软字幕")
        else:
            # 字幕不足但原因不明 (非视频平台等)
            result["hard_embedded_subs"] = True
            result["subtitle_status"] = "unknown"
            log.info("字幕不足 (%d 字), 标记为疑似硬字幕", subs_len)

        # 构建 Markdown
        parts = []
        vt = result.get("video_title")
        if vt:
            parts.append(f"# {vt}")
        vd = result.get("video_description")
        if vd:
            parts.append(f"> {vd}")
        subs = result.get("subtitles")
        if subs and len(subs) > 50:
            parts.append(f"\n## 字幕/转录\n\n{subs[:20000]}")
        elif subs_len := len(result.get("subtitles", "")):
            log.info("字幕不足 (%d 字), 仅返回元数据", subs_len)

        text = "\n\n".join(parts)
        result["markdown"] = text
        result["plain_text"] = text
        result["text_length"] = len(text)
        return result

    # ── Step 1: 字幕提取 (扩展 content script + yt-dlp 增强) ──

    def _extract_subtitles(self, url):
        """
        提取字幕+元数据。
        优先用 extension content script 已提取的 media_meta (带cookie),
        yt-dlp 作为可选增强 (需要浏览器 cookie 才能访问B站/YouTube).
        """
        # 先用 yt-dlp 尝试 (可能因 cookie/captcha 失败)
        yt_result = self._try_yt_dlp(url)
        if yt_result and yt_result.get("text") and len(yt_result["text"]) > 50:
            log.info("[Phase2] yt-dlp 字幕: %d 字", len(yt_result["text"]))
            return yt_result
        # yt-dlp 失败或字幕不足 -> 返回部分元数据
        if yt_result:
            log.info("[Phase2] yt-dlp 元数据可用 (无字幕)")
        return yt_result  # None 或只有元数据

    def _try_yt_dlp(self, url):
        """yt-dlp 提取字幕 (可能因反爬失败)"""
        try:
            import yt_dlp
        except ImportError:
            return None

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                ydl_opts = {
                    'skip_download': True,
                    'writesubtitles': True,
                    'writeautosub': True,
                    'subtitlesformat': 'srt',
                    'subtitleslangs': ['zh-Hans', 'zh', 'en', 'ai-zh', 'ai-en'],
                    'outtmpl': f'{tmpdir}/%(id)s.%(ext)s',
                    'quiet': True, 'no_warnings': True,
                }

                # 尝试从浏览器读取 cookie (仅在不运行时有效)
                for browser in [('chrome',), ('edge',)]:
                    try:
                        ydl_opts['cookiesfrombrowser'] = browser
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                        break
                    except Exception:
                        continue
                else:
                    # 无 cookie, 尝试直接访问
                    ydl_opts.pop('cookiesfrombrowser', None)
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)

                result = self._build_subtitle_result(info, tmpdir)
                return result

        except Exception as e:
            log.debug("[Phase2] yt-dlp 不可用: %s", str(e)[:80])
            return None

    def _build_subtitle_result(self, info, tmpdir):
        """从 yt-dlp info 构建结果"""
        result = {
            "title": info.get("title", ""),
            "description": (info.get("description") or "")[:2000],
            "duration": info.get("duration", 0) or 0,
            "uploader": info.get("uploader", "") or "",
            "text": "", "language": "",
        }
        video_id = info.get("id", "")
        srt_files = list(Path(tmpdir).glob(f"{video_id}*.srt"))
        if not srt_files:
            srt_files = list(Path(tmpdir).glob("*.srt"))

        if srt_files:
            srt_path = srt_files[0]
            result["language"] = self._guess_lang(srt_path.name)
            raw = srt_path.read_text(encoding="utf-8")
            result["text"] = self._parse_srt(raw)
        else:
            subs = info.get("subtitles") or info.get("automatic_captions") or {}
            if subs:
                lang = list(subs.keys())[0]
                result["language"] = lang
        return result

    # ── Step 2: 语音转文字降级 (硬字幕) ────────────────────

    def _transcribe_audio(self, audio_url: str, ext_meta: dict = None) -> str | None:
        """
        下载 B站 DASH 音频流 + faster-whisper 转写。

        使用项目本地的 audio_transcriber 模块，模型自动下载到 whisper_model_dir。
        返回转写文本, 失败返回 None。
        """
        import tempfile
        import urllib.request
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            audio_path = tmpdir / "audio.m4a"

            # 1. 下载音频流
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
            }
            try:
                req = urllib.request.Request(audio_url, headers=headers)
                resp = urllib.request.urlopen(req, timeout=120)
                audio_data = resp.read()
                if len(audio_data) < 50_000:  # < 50KB == 异常
                    log.warning("音频下载异常: 仅 %d 字节", len(audio_data))
                    return None
                audio_path.write_bytes(audio_data)
                size_mb = len(audio_data) / (1024 * 1024)
                log.info("音频下载完成: %.1fMB", size_mb)
            except Exception as e:
                log.warning("音频下载失败: %s", e)
                # 尝试备用 URL
                backups = (ext_meta or {}).get("bilibili_audio_backups", [])
                for backup_url in backups:
                    try:
                        log.info("尝试备用 URL...")
                        req = urllib.request.Request(backup_url, headers=headers)
                        resp = urllib.request.urlopen(req, timeout=120)
                        audio_data = resp.read()
                        if len(audio_data) > 50_000:
                            audio_path.write_bytes(audio_data)
                            break
                    except Exception:
                        continue
                else:
                    log.warning("所有音频 URL 均失败")
                    return None

            # 2. faster-whisper 转写
            try:
                from audio_transcriber import transcribe as whisper_transcribe
                from config import get_config
                cfg = get_config()
                segments = whisper_transcribe(
                    audio_path,
                    model_name="medium",
                    language="zh",
                    device="cpu",
                    model_dir=cfg.whisper_model_dir or None,
                )
                text = "\n".join(seg["text"] for seg in segments)
                log.info("语音转写完成: %d 字, %d 段", len(text), len(segments))
                return text
            except Exception as e:
                log.error("语音转写失败: %s", e)
                return None

    # ── 辅助 ────────────────────────────────────────────────

    @staticmethod
    def _parse_srt(srt_text):
        """SRT -> 纯文本"""
        lines = []
        for line in srt_text.split('\n'):
            line = line.strip()
            if not line or '-->' in line or line.isdigit():
                continue
            text = line.split('<', 1)[0] if '<' in line else line
            text = text.strip()
            if text and text not in ('[Music]', '[Applause]',
                                     '[音乐]', '[鼓掌]'):
                lines.append(text)
        return '\n'.join(lines)

    @staticmethod
    def _guess_lang(filename):
        """从文件名猜测字幕语言"""
        n = filename.lower()
        for k in ['zh-hans', 'zh-cn', 'chs', 'chinese', 'ai-zh']:
            if k in n:
                return 'zh'
        for k in ['en', 'english', 'ai-en']:
            if k in n:
                return 'en'
        if 'ja' in n:
            return 'ja'
        return 'unknown'
