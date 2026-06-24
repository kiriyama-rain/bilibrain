"""
外脑知识库写入器 — 保存捕获内容到知识库
=======================================
格式兼容 raw/视频与博客/ 和 wiki/摘要/ 的规范。
路径通过 config.py 配置。
"""
import re
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    from config import get_config
    _cfg = get_config()
    OUTBRAIN_DIR = Path(_cfg.outbrain_dir)
    RAW_DIR = OUTBRAIN_DIR / _cfg.raw_clippings_subdir
    WIKI_DIR = OUTBRAIN_DIR / _cfg.wiki_subdir
except Exception:
    # 回退: config 不可用时使用默认路径
    OUTBRAIN_DIR = Path.home() / "外脑"
    RAW_DIR = OUTBRAIN_DIR / "raw" / "视频与博客"
    WIKI_DIR = OUTBRAIN_DIR / "wiki"

INDEX_FILE = WIKI_DIR / "index.md"
LOG_FILE = WIKI_DIR / "log.md"

from logger import get_logger
log = get_logger(__name__)


def sanitize_filename(title: str) -> str:
    """从标题生成合法文件名"""
    name = re.sub(r'[<>:"/\\|?*]', "", title)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 80:
        name = name[:80]
    return name if name else "未命名"


def write_raw_clip(
    url: str, title: str, markdown: str,
    metadata: dict = None, author: str = "",
    published: str = "",
) -> str:
    """写入 raw/视频与博客/，返回文件路径"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    domain = urlparse(url).netloc.replace("www.", "").split(".")[0]
    filename = f"{sanitize_filename(title)}-{domain}.md"
    filepath = RAW_DIR / filename

    if filepath.exists():
        filepath = RAW_DIR / f"{sanitize_filename(title)}-{domain}-{int(time.time())}.md"

    meta = metadata or {}
    md = markdown or ""
    desc = (meta.get('description') or md)[:100].replace('"', "'")

    content = f"""---
title: "{title}"
source: "{url}"
author: "{author or meta.get('author', '')}"
published: "{published or meta.get('published', '')}"
created: "{time.strftime('%Y-%m-%d')}"
description: "{desc}"
tags:
  - "clippings"
---

{md}
"""
    filepath.write_text(content, encoding="utf-8")
    log.info(f"Raw clip saved: {filepath}")
    return str(filepath)


def write_wiki_summary(
    raw_path: str, title: str, url: str,
    summary: str, tags: list = None,
) -> str:
    """写入 wiki/摘要/，返回文件路径"""
    wiki_summary_dir = WIKI_DIR / "摘要"
    wiki_summary_dir.mkdir(parents=True, exist_ok=True)

    raw_filename = Path(raw_path).name
    summary_title = raw_filename.replace(".md", "")

    filename = f"{summary_title}.md"
    filepath = wiki_summary_dir / filename

    if filepath.exists():
        filepath = wiki_summary_dir / f"{summary_title}-{int(time.time())}.md"

    tags_str = ", ".join(tags or ["摘要"])
    content = f"""---
title: {summary_title}
tags: [{tags_str}]
created: {time.strftime('%Y-%m-%d')}
updated: {time.strftime('%Y-%m-%d')}
source: raw/视频与博客/{raw_filename}
aliases: []
---

# {title}

> 来源：[{title}]({url})

{summary}
"""
    filepath.write_text(content, encoding="utf-8")
    log.info(f"Wiki summary saved: {filepath}")
    return str(filepath)


def update_index(new_entry: str, category: str = "摘要"):
    """更新 wiki/index.md"""
    if not INDEX_FILE.exists():
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        INDEX_FILE.write_text("# Wiki Index\n\n", encoding="utf-8")

    lines = INDEX_FILE.read_text(encoding="utf-8").split("\n")

    section_found = False
    new_lines = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if f"## {category}" in line:
            section_found = True
        elif section_found and not inserted:
            if line.strip().startswith("- ") or line.strip() == "":
                new_lines.append(f"  - {new_entry}")
                inserted = True
            elif line.startswith("#") and line != f"## {category}":
                new_lines.append(f"  - {new_entry}")
                inserted = True

    if not inserted:
        new_lines.append(f"\n## {category}")
        new_lines.append(f"  - {new_entry}")

    INDEX_FILE.write_text("\n".join(new_lines), encoding="utf-8")


def append_log(action: str, details: dict):
    """追加日志到 wiki/log.md"""
    if not LOG_FILE.exists():
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.write_text("# 变更日志\n\n", encoding="utf-8")

    log_entry = f"""## [{time.strftime('%Y-%m-%d %H:%M')}] {action}
- **文件**: {details.get('file', 'N/A')}
- **标题**: {details.get('title', 'N/A')}
- **来源**: {details.get('url', 'N/A')}
- **类型**: {details.get('type', 'clippings')}

"""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)


def save_capture(
    url: str, title: str, markdown: str,
    metadata: dict = None,
    with_wiki: bool = False,
    summary: str = "",
    tags: list = None,
) -> dict:
    """一键保存捕获内容到外脑，返回保存结果"""
    result = {"success": False}

    try:
        # 1. 写入 raw
        raw_path = write_raw_clip(url, title, markdown, metadata)
        result["raw_file"] = raw_path

        # 2. 可选：写入 wiki 摘要
        wiki_path = None
        if with_wiki and summary:
            wiki_path = write_wiki_summary(raw_path, title, url, summary, tags)
            result["wiki_file"] = wiki_path

        # 3. 更新索引
        entry_name = f"[{title}](raw/视频与博客/{Path(raw_path).name})"
        update_index(entry_name, "网络剪藏")
        if wiki_path:
            wiki_entry = f"[{title}](wiki/摘要/{Path(wiki_path).name})"
            update_index(wiki_entry, "摘要")

        # 4. 追加日志
        append_log("摄入", {
            "file": raw_path,
            "title": title,
            "url": url,
            "type": "clippings",
        })

        result["success"] = True
        result["message"] = "已保存到外脑知识库"

    except Exception as e:
        result["error"] = str(e)
        log.error(f"保存失败: {e}")

    return result
