"""
测试: 音频下载 + faster-whisper 转写 (硬字幕降级方案)
=====================================================
用 B站 DASH 音频 URL 下载 -> faster-whisper 转写
"""
import sys
import time
import tempfile
from pathlib import Path

# 使用项目本地的 audio_transcriber 模块
from audio_transcriber import (
    transcribe, write_srt, write_text,
    format_timestamp, get_default_model_dir,
)


def download_audio(audio_url: str, output_path: Path) -> bool:
    """下载 B站 DASH 音频流 (m4a 格式)"""
    import urllib.request

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    req = urllib.request.Request(audio_url, headers=headers)
    print(f"[下载] 正在下载音频流...")

    try:
        resp = urllib.request.urlopen(req, timeout=120)
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(output_path, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded * 100 // total
                    print(f"\r  进度: {downloaded//1024}KB / {total//1024}KB ({pct}%)", end="")
        print(f"\n  完成! {downloaded//1024}KB")
        return True
    except Exception as e:
        print(f"\n[错误] 下载失败: {e}")
        return False


def test_transcribe_from_url(audio_url: str):
    """端到端测试: 下载音频 -> 转写"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        audio_path = tmpdir / "audio.m4a"

        # Step 1: 下载
        if not download_audio(audio_url, audio_path):
            return None

        # Step 2: 检查音频文件
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        print(f"[检查] 音频文件: {size_mb:.1f}MB")

        if size_mb < 0.1:
            print("[错误] 音频文件太小, 可能下载失败")
            return None

        # Step 3: faster-whisper 转写
        print(f"[转写] 使用 faster-whisper small 模型转写...")
        start = time.time()
        try:
            segments = transcribe(
                audio_path,
                model_name="small",
                language="zh",
                device="cpu",
            )
            elapsed = time.time() - start
            print(f"[完成] 转写耗时: {elapsed:.1f}s, 共 {len(segments)} 段")

            # 输出前 20 段看看质量
            print(f"\n{'='*60}")
            print(f"转写结果预览 (前 20 段):")
            print(f"{'='*60}")
            for seg in segments[:20]:
                ts = format_timestamp(seg["start"])
                print(f"[{ts}] {seg['text']}")

            if len(segments) > 20:
                print(f"... (共 {len(segments)} 段)")

            # 输出完整文本
            full_text = "\n".join(seg["text"] for seg in segments)
            print(f"\n总字数: {len(full_text)}")
            return segments

        except Exception as e:
            print(f"[错误] 转写失败: {e}")
            import traceback
            traceback.print_exc()
            return None


if __name__ == "__main__":
    # 测试 URL — 需要从 extension 捕获的实际 B站 音频 URL
    # 格式: https://xy123x123x123.xxxx/m4s/...
    if len(sys.argv) < 2:
        print("用法: python test_whisper_fallback.py <bilibili_audio_url>")
        print()
        print("获取 URL 方法:")
        print("  1. 用 Chrome 打开 B站视频")
        print("  2. F12 -> Network -> 搜索 m4s")
        print("  3. 找 audio/30280/m4s 类型的请求 -> Copy URL")
        print("  或: 用 Browser Brain 扩展捕获后会打印 audio_url")
        sys.exit(1)

    audio_url = sys.argv[1]
    test_transcribe_from_url(audio_url)
