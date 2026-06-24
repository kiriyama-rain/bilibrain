"""
转写 API: POST /api/transcribe
==============================
视频文件 -> PaddleOCR 硬字幕提取 (SSE 实时进度)
音频文件 -> faster-whisper 语音转文字
"""
import json
import queue
import tempfile
import threading
from pathlib import Path

from flask import Blueprint, request, jsonify, Response

from logger import get_logger

log = get_logger(__name__)
transcribe_bp = Blueprint("transcribe", __name__)

AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma'}
VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4s'}
ALLOWED_EXTS = AUDIO_EXTS | VIDEO_EXTS
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB

# faster-whisper 模型路径通过 config 或默认目录
from audio_transcriber import transcribe as whisper_transcribe, get_default_model_dir


@transcribe_bp.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    """接收音频/视频文件并转写"""
    if 'file' not in request.files:
        return jsonify({"error": "缺少文件"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        return jsonify({"error": f"不支持的格式: {ext}"}), 400

    # 使用持久化的临时目录 (不能用 TemporaryDirectory, 因为 SSE 流在函数返回后才执行)
    import uuid
    persist_dir = Path(tempfile.gettempdir()) / f"bb_transcribe_{uuid.uuid4().hex[:8]}"
    persist_dir.mkdir(parents=True, exist_ok=True)

    save_path = persist_dir / f"upload{ext}"
    file.save(str(save_path))

    size_mb = save_path.stat().st_size / (1024 * 1024)
    if save_path.stat().st_size > MAX_FILE_SIZE:
        import shutil
        shutil.rmtree(persist_dir, ignore_errors=True)
        return jsonify({"error": "文件太大 (最大 500MB)"}), 400

    # ── 视频: PaddleOCR 硬字幕提取 ──
    if ext in VIDEO_EXTS:
        def cleanup_and_stream():
            try:
                yield from _transcribe_video_generator(save_path, size_mb)
            finally:
                import shutil
                shutil.rmtree(persist_dir, ignore_errors=True)
        return Response(
            cleanup_and_stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── 音频: faster-whisper 语音转文字 ──
    else:
        try:
            return _transcribe_audio(save_path, size_mb)
        finally:
            import shutil
            shutil.rmtree(persist_dir, ignore_errors=True)


def _transcribe_video_generator(video_path: Path, size_mb: float):
    """PaddleOCR 硬字幕提取 - SSE 流式返回进度 (生成器)"""
    log.info(f"视频硬字幕提取: {video_path.name} ({size_mb:.1f}MB)")

    from hardsub_extractor import extract_subtitles

    progress_queue = queue.Queue()
    result = {"text": None, "error": None}

    def progress_callback(stage, current, total):
        progress_queue.put({"stage": stage, "current": current, "total": total})

    def run_ocr():
        try:
            result["text"] = extract_subtitles(
                str(video_path), progress_callback=progress_callback
            )
        except Exception as e:
            result["error"] = str(e)

    thread = threading.Thread(target=run_ocr, daemon=True)
    thread.start()

    # SSE 事件流
    yield "data: " + json.dumps({"stage": "init", "message": "开始提取帧 + OCR 识别..."},
                                 ensure_ascii=False) + "\n\n"

    while thread.is_alive() or not progress_queue.empty():
        try:
            evt = progress_queue.get(timeout=1)
            yield "data: " + json.dumps({
                "stage": evt["stage"],
                "current": evt["current"],
                "total": evt["total"],
                "percent": round(evt["current"] * 100 / max(evt["total"], 1)),
            }, ensure_ascii=False) + "\n\n"
        except queue.Empty:
            yield ": keepalive\n\n"

    thread.join()

    if result["error"]:
        log.error(f"硬字幕提取失败: {result['error']}")
        yield "data: " + json.dumps({"error": result["error"]}, ensure_ascii=False) + "\n\n"
    elif result["text"]:
        text = result["text"]
        lines = text.split('\n')
        char_count = len(text)
        seg_count = len(lines)
        method = "PaddleOCR (硬字幕)"

        # 自动持久化
        try:
            from capture_store import save_transcription
            tid = save_transcription(text, char_count, seg_count, method)
            log.info(f"硬字幕提取完成: {char_count} 字, {seg_count} 条 (id={tid[:8]})")
        except Exception as e:
            log.error(f"转写保存失败: {e}")
            tid = None

        yield "data: " + json.dumps({
            "done": True,
            "id": tid,
            "text": text,
            "char_count": char_count,
            "segment_count": seg_count,
            "method": method,
        }, ensure_ascii=False) + "\n\n"
    else:
        yield "data: " + json.dumps({"error": "未知错误"}, ensure_ascii=False) + "\n\n"


# ── 转写历史查询 ──────────────────────────────────────────

@transcribe_bp.route("/api/transcriptions")
def api_list_transcriptions():
    """列出最近的转写记录"""
    try:
        from capture_store import list_transcriptions
        items = list_transcriptions(limit=20)
        return jsonify(items)
    except Exception as e:
        log.exception("获取转写列表失败")
        return jsonify({"error": str(e)}), 500


@transcribe_bp.route("/api/transcriptions/<tid>")
def api_get_transcription(tid: str):
    """获取完整转写内容"""
    try:
        from capture_store import get_transcription
        item = get_transcription(tid)
        if item is None:
            return jsonify({"error": "转写记录不存在"}), 404
        return jsonify(item)
    except Exception as e:
        log.exception("获取转写详情失败")
        return jsonify({"error": str(e)}), 500


def _transcribe_audio(audio_path: Path, size_mb: float):
    """faster-whisper 语音转文字"""
    log.info(f"语音转写: {audio_path.name} ({size_mb:.1f}MB)")

    try:
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
        char_count = len(text)
        seg_count = len(segments)
        method = "faster-whisper (语音)"

        # 自动持久化
        tid = None
        try:
            from capture_store import save_transcription
            tid = save_transcription(text, char_count, seg_count, method)
        except Exception as e:
            log.error(f"转写保存失败: {e}")

        log.info(f"转写完成: {char_count} 字, {seg_count} 段")
        return jsonify({
            "id": tid,
            "text": text,
            "char_count": char_count,
            "segment_count": seg_count,
            "method": method,
        })
    except ImportError as e:
        log.error(f"faster-whisper 不可用: {e}")
        return jsonify({"error": "faster-whisper 未安装"}), 500
    except Exception as e:
        log.exception("语音转写失败")
        return jsonify({"error": f"语音转写失败: {e}"}), 500
