"""
硬字幕提取 — 基于 PaddleOCR 从视频帧中识别画面内嵌字幕
========================================================
流程: 视频 -> ffmpeg 截图 -> 裁剪字幕区域 -> PaddleOCR -> 去重 -> 字幕文本

用法: python hardsub_extractor.py <video_file>
"""
import os
import sys
import subprocess
import tempfile
import time
from pathlib import Path

os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'

def _find_ffmpeg() -> str:
    """Auto-detect ffmpeg executable path.

    Priority: config.ffmpeg_path > PATH > Windows common locations.
    """
    import shutil

    # 1. Check config
    try:
        from config import get_config
        cfg = get_config()
        if cfg.ffmpeg_path and Path(cfg.ffmpeg_path).exists():
            return cfg.ffmpeg_path
    except Exception:
        pass

    # 2. Check PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    # 3. Windows common locations
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages"),
            Path("C:/", "ffmpeg", "bin", "ffmpeg.exe"),
            Path(os.environ.get("ProgramFiles", "C:/Program Files"), "ffmpeg", "bin", "ffmpeg.exe"),
        ]
        # Walk WinGet packages for ffmpeg
        winget_root = Path(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
        if winget_root.exists():
            for d in winget_root.iterdir():
                if d.is_dir() and "ffmpeg" in d.name.lower():
                    exe = d / "bin" / "ffmpeg.exe"
                    if exe.exists():
                        return str(exe)
                    # Some versions have nested dirs
                    for sub in d.glob("**/ffmpeg.exe"):
                        return str(sub)

    raise RuntimeError(
        "FFmpeg not found. Install from https://ffmpeg.org/ or set ffmpeg_path in config.json"
    )


# Resolve ffmpeg at import time (cached)
_FFMPEG_PATH = None
FPS = 0.5  # 每 2 秒取一帧
SUBTITLE_BOTTOM_RATIO = 0.22  # 底部 22% 为字幕区域
OCR_CONFIDENCE = 0.3  # OCR 置信度阈值
OCR_LANG = 'ch'  # 中文简体
OCR_DET_MODEL = 'PP-OCRv5_mobile_det'  # mobile 版检测模型 (快, ~0.4s/帧)
OCR_REC_MODEL = 'PP-OCRv5_mobile_rec'  # mobile 版识别模型 (快)


def extract_frames(video_path: Path, output_dir: Path) -> list[Path]:
    """ffmpeg 抽取视频帧"""
    global _FFMPEG_PATH
    if _FFMPEG_PATH is None:
        _FFMPEG_PATH = _find_ffmpeg()
    cmd = [
        _FFMPEG_PATH, "-i", str(video_path),
        "-vf", f"fps={FPS}",
        "-q:v", "2",
        "-y", str(output_dir / "frame_%06d.jpg"),
    ]
    print(f"[ffmpeg] 抽取帧: {video_path.name} (fps={FPS})")
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding='utf-8', errors='replace',
    )
    if result.returncode != 0:
        err = (result.stderr or '')[:500]
        raise RuntimeError(f"ffmpeg failed: {err}")
    frames = sorted(output_dir.glob("frame_*.jpg"))
    print(f"  -> {len(frames)} 帧")
    return frames


def crop_subtitle_region(frame_path: Path, output_path: Path):
    """裁剪画面底部字幕区域"""
    from PIL import Image
    img = Image.open(frame_path)
    w, h = img.size
    crop_h = int(h * SUBTITLE_BOTTOM_RATIO)
    cropped = img.crop((0, h - crop_h, w, h))
    # 放大 2 倍提高 OCR 精度 (720p 以下建议放大)
    if max(w, h) < 1280:
        cropped = cropped.resize((cropped.width * 2, cropped.height * 2), Image.LANCZOS)
    cropped.save(output_path, quality=95)
    return cropped


def ocr_frame(ocr, frame_path: Path) -> str:
    """PaddleOCR 识别单帧字幕"""
    try:
        result = ocr.predict(str(frame_path))
        texts = result[0].get('rec_texts', [])
        scores = result[0].get('rec_scores', [])
        lines = []
        for text, score in zip(texts, scores):
            if score >= OCR_CONFIDENCE:
                t = text.strip()
                if t:
                    lines.append(t)
        return ' '.join(lines)
    except Exception as e:
        # PaddleOCR 在某些帧上可能报错，跳过
        return ''


def deduplicate_subtitles(subtitle_list: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """
    去重: 相邻帧文字相同则合并，保留首次出现的时间戳。
    输入: [(timestamp_seconds, 'text'), ...]
    输出: 去重后的列表
    """
    if not subtitle_list:
        return []

    result = []
    prev_text = None
    for ts, text in subtitle_list:
        if text and text != prev_text:
            result.append((ts, text))
            prev_text = text

    return result


def extract_subtitles(video_path: str, progress_callback=None) -> str:
    """
    主流程: 从视频中提取硬字幕。

    Args:
        video_path: 视频文件路径
        progress_callback: 可选的进度回调, 签名为 callback(stage, current, total)
            stage: 'frames' | 'ocr'
    """
    video = Path(video_path)
    if not video.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    print(f"\n{'='*60}")
    print(f"硬字幕提取: {video.name}")
    print(f"{'='*60}")

    start = time.time()

    # PaddleOCR 初始化 (mobile 模型 + 跳过文档校正)
    from paddleocr import PaddleOCR
    try:
        ocr = PaddleOCR(
            lang=OCR_LANG,
            text_detection_model_name=OCR_DET_MODEL,
            text_recognition_model_name=OCR_REC_MODEL,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except Exception as e:
        print(f"[错误] PaddleOCR 初始化失败: {e}")
        raise

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        frames_dir = tmpdir / "frames"
        crops_dir = tmpdir / "crops"
        frames_dir.mkdir()
        crops_dir.mkdir()

        # Step 1: 抽取帧
        frames = extract_frames(video, frames_dir)

        # Step 2: 逐帧裁剪 + OCR
        raw_subs = []
        for i, frame_path in enumerate(frames):
            ts = i / FPS  # 当前帧对应的时间点

            crop_path = crops_dir / f"crop_{i:06d}.jpg"
            try:
                crop_subtitle_region(frame_path, crop_path)
            except Exception as e:
                print(f"  [{i}/{len(frames)}] 裁剪失败: {e}")
                continue

            text = ocr_frame(ocr, crop_path)
            raw_subs.append((ts, text))

            if progress_callback:
                progress_callback('ocr', i + 1, len(frames))
            elif (i + 1) % 50 == 0 or i == len(frames) - 1:
                elapsed = time.time() - start
                eta = (elapsed / (i + 1)) * (len(frames) - i - 1)
                print(f"  [{i+1}/{len(frames)}] 进度 ({elapsed:.0f}s elapsed, ETA {eta:.0f}s)", end='\r')

        # Step 3: 去重
        cleaned = deduplicate_subtitles(raw_subs)

        # Step 4: 格式化输出
        lines = []
        for ts, text in cleaned:
            m, s = int(ts // 60), int(ts % 60)
            lines.append(f"[{m}:{s:02d}] {text}")

        result = '\n'.join(lines)
        elapsed = time.time() - start
        print(f"\n完成! {elapsed:.0f}s | {len(frames)} 帧 -> {len(cleaned)} 条字幕 | {len(result)} 字")
        return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python hardsub_extractor.py <视频文件>")
        print("示例: python hardsub_extractor.py D:/path/to/video.mp4")
        sys.exit(1)

    text = extract_subtitles(sys.argv[1])
    print(f"\n{'='*60}")
    print("提取结果预览 (前 30 条):")
    print(f"{'='*60}")
    lines = text.split('\n')
    for line in lines[:30]:
        print(line)
    if len(lines) > 30:
        print(f"... (共 {len(lines)} 条)")

    # 保存结果
    out_path = Path(sys.argv[1]).with_suffix('.hardsub.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"\n已保存到: {out_path}")
