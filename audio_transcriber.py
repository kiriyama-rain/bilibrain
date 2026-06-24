"""
Audio transcriber using faster-whisper.
=======================================
Self-contained wrapper — no external dependencies beyond faster-whisper.
Models are auto-downloaded on first use to the configurable model directory.

Usage:
    from audio_transcriber import transcribe, format_timestamp, write_srt, write_text

    segments = transcribe(audio_path, model_name="medium", language="zh")
    for seg in segments:
        print(f"[{format_timestamp(seg['start'])}] {seg['text']}")
"""
import time
from pathlib import Path


def get_default_model_dir() -> Path:
    """Default model cache directory (~/.browser-brain/whisper-models)."""
    return Path.home() / ".browser-brain" / "whisper-models"


def transcribe(
    audio_path,
    model_name: str = "medium",
    language: str = "zh",
    device: str = "cpu",
    model_dir: str = None,
) -> list[dict]:
    """
    Transcribe audio using faster-whisper.

    Args:
        audio_path: Path to audio file (str or Path).
        model_name: Model size — "tiny", "base", "small", "medium", "large-v3".
        language: Language code ("zh", "en", etc.) or None for auto-detect.
        device: "cpu" or "cuda".
        model_dir: Custom model cache directory. Defaults to ~/.browser-brain/whisper-models.

    Returns:
        List of dicts: [{"start": float, "end": float, "text": str}, ...]
    """
    from faster_whisper import WhisperModel

    models_dir = model_dir or str(get_default_model_dir())

    print(f"[模型] 加载 faster-whisper 模型: {model_name} (设备: {device})")
    start = time.time()

    model = WhisperModel(
        model_name,
        device=device,
        compute_type="int8" if device == "cpu" else "float16",
        download_root=models_dir,
        cpu_threads=4,
        num_workers=2,
    )
    print(f"   [OK] 模型加载完成 ({time.time() - start:.1f}s)")

    lang_display = language if language else "自动检测"
    print(f"[转写] 转写中... (语言: {lang_display})")
    start = time.time()

    lang_param = None if language == "auto" else language
    segments_gen, info = model.transcribe(
        str(audio_path),
        language=lang_param,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    duration = info.duration
    detected_lang = info.language
    print(f"   [OK] 转写完成! ({time.time() - start:.1f}s)")
    print(f"   [信息] 音频时长: {duration:.1f}s | 检测语言: {detected_lang} "
          f"(概率: {info.language_probability:.2%})")

    result = []
    for seg in segments_gen:
        result.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
        })

    return result


def format_timestamp(seconds: float) -> str:
    """Format seconds as SRT timestamp (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list[dict], output_path: Path) -> None:
    """Write segments as SRT subtitle file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(seg['start'])} --> {format_timestamp(seg['end'])}\n")
            f.write(f"{seg['text']}\n\n")
    print(f"[文件] SRT 字幕已保存: {output_path}")


def write_text(segments: list[dict], output_path: Path) -> None:
    """Write segments as plain text file (text only, no timestamps)."""
    with open(output_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(seg["text"] + "\n")
    print(f"[文件] 纯文本已保存: {output_path}")
