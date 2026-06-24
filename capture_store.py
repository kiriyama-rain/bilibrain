"""
捕获持久化存储 (SQLite)
========================
将每次捕获页面自动存入 SQLite, 支持服务重启后恢复历史记录。

设计:
  - 每次 POST /api/capture 成功后自动写入
  - 列表 API 仅返回前 200 字预览 (避免大 payload)
  - 详情 API 返回完整内容 (按需加载)
  - WAL 模式支持并发读取
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config import get_config
from logger import get_logger

log = get_logger(__name__)

# ─── 内部辅助 ──────────────────────────────────────────

def _get_db_path() -> Path:
    """返回 SQLite 数据库路径, 确保父目录存在"""
    cfg = get_config()
    p = Path(cfg.sqlite_db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _get_conn() -> sqlite3.Connection:
    """创建数据库连接, 初始化表结构, 启用 WAL"""
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection):
    """创建 captures 表和索引 (幂等)"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS captures (
            id           TEXT PRIMARY KEY,
            url          TEXT NOT NULL,
            title        TEXT NOT NULL DEFAULT '',
            markdown     TEXT NOT NULL DEFAULT '',
            plain_text   TEXT NOT NULL DEFAULT '',
            content_type TEXT NOT NULL DEFAULT 'webpage',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            captured_via TEXT NOT NULL DEFAULT 'extension',
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_captures_created_at
        ON captures(created_at DESC)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcriptions (
            id           TEXT PRIMARY KEY,
            text         TEXT NOT NULL DEFAULT '',
            char_count   INTEGER NOT NULL DEFAULT 0,
            segment_count INTEGER NOT NULL DEFAULT 0,
            method       TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_transcriptions_created_at
        ON transcriptions(created_at DESC)
    """)
    conn.commit()


# ─── 公共 API ──────────────────────────────────────────

def save_capture(
    url: str,
    title: str,
    markdown: str = "",
    plain_text: str = "",
    content_type: str = "webpage",
    metadata: dict = None,
    captured_via: str = "extension",
) -> str:
    """
    持久化一条捕获记录到 SQLite。

    Returns:
        capture_id (UUID4 字符串)
    """
    capture_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO captures
               (id, url, title, markdown, plain_text, content_type,
                metadata_json, captured_via, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (capture_id, url, title, markdown, plain_text, content_type,
             metadata_json, captured_via, created_at),
        )
        conn.commit()
        log.info(f"Capture saved to DB: {capture_id[:8]} — {title[:60]}")
        return capture_id
    except Exception as e:
        log.error(f"Failed to save capture: {e}")
        raise
    finally:
        conn.close()


def list_captures(limit: int = 50, offset: int = 0) -> dict:
    """
    列出最近的捕获记录 (仅返回前 200 字预览)。

    Returns:
        {"captures": [...], "total": int, "limit": int, "offset": int}
    """
    conn = _get_conn()
    try:
        total_row = conn.execute("SELECT COUNT(*) FROM captures").fetchone()
        total = total_row[0] if total_row else 0

        rows = conn.execute(
            """SELECT id, url, title, content_type, captured_via,
                      created_at, substr(plain_text, 1, 200) AS preview
               FROM captures
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()

        captures = [dict(r) for r in rows]
        return {"captures": captures, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


def get_capture(capture_id: str) -> dict | None:
    """
    获取单条捕获的完整内容。

    Returns:
        dict (含所有字段) 或 None (未找到)
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM captures WHERE id = ?", (capture_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        # 反序列化元数据
        try:
            result["metadata"] = json.loads(result.get("metadata_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            result["metadata"] = {}
        if "metadata_json" in result:
            del result["metadata_json"]
        return result
    finally:
        conn.close()


def delete_capture(capture_id: str) -> bool:
    """
    删除一条捕获记录。

    Returns:
        True 如果删除成功, False 如果记录不存在
    """
    conn = _get_conn()
    try:
        cursor = conn.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            log.info(f"Capture deleted: {capture_id[:8]}")
        return deleted
    finally:
        conn.close()


# ─── 转写记录 ──────────────────────────────────────────

def save_transcription(text: str, char_count: int, segment_count: int,
                       method: str = "") -> str:
    """保存转写结果, 返回 id"""
    capture_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO transcriptions
               (id, text, char_count, segment_count, method, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (capture_id, text, char_count, segment_count, method, created_at),
        )
        conn.commit()
        log.info(f"Transcription saved: {capture_id[:8]} — {char_count} chars")
        return capture_id
    finally:
        conn.close()


def list_transcriptions(limit: int = 20) -> list[dict]:
    """列出最近的转写记录 (仅返回预览)"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT id, char_count, segment_count, method,
                      created_at, substr(text, 1, 100) AS preview
               FROM transcriptions
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_transcription(tid: str) -> dict | None:
    """获取完整转写内容"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM transcriptions WHERE id = ?", (tid,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_transcription(tid: str) -> bool:
    """删除转写记录"""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM transcriptions WHERE id = ?", (tid,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
