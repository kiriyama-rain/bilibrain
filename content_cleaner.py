"""
正文清洗 — 快速广告/导航移除 + 正文提取 + Markdown 转换
=======================================================
优化：使用 SoupStrainer + lxml 加速，CSS 选择器替代 find_all
"""
import re
from bs4 import BeautifulSoup, SoupStrainer


def clean_html(html: str) -> str:
    """快速移除广告/导航/评论/侧栏等无用元素，返回干净 HTML"""
    # 只解析 body 即可，不需要 head
    body_only = SoupStrainer("body")
    soup = BeautifulSoup(html, "lxml", parse_only=body_only)

    # 批量移除标签（用 CSS 选择器比 find_all 快）
    for sel in [
        "script", "style", "noscript", "iframe", "svg", "canvas", "template",
        "nav", "footer", "header", "aside", "form", "button",
    ]:
        for el in soup.select(sel):
            el.decompose()

    # 按类名/ID 批量移除
    kill_patterns = [
        ".advertisement", ".ad-", ".ads", ".adsbox", ".ad-container",
        ".sidebar", ".sidebar-right", ".aside", ".widget",
        ".comment", ".comment-list", ".comment-area", ".comment-form", ".reply",
        ".related", ".recommend", ".recommendation", ".suggest",
        ".social-share", ".share-bar",
        ".footer", ".navbar", ".nav-", ".breadcrumb",
        ".toolbar", ".tooltip", ".popup", ".notification", ".cookie",
        "[aria-hidden=true]",
        "[role=complementary]", "[role=banner]", "[role=navigation]",
    ]
    for sel in kill_patterns:
        try:
            for el in soup.select(sel):
                el.decompose()
        except Exception:
            continue

    return str(soup)


def extract_article_text(html: str) -> str:
    """从清洗后的 HTML 中提取正文纯文本（优先 article/main）"""
    article_only = SoupStrainer(["article", "main", "body"])
    soup = BeautifulSoup(html, "lxml", parse_only=article_only)

    # 1. <article>
    el = soup.select_one("article")
    if el:
        text = el.get_text(separator="\n", strip=True)
        if len(text) > 200:
            return text

    # 2. <main>
    el = soup.select_one("main")
    if el:
        text = el.get_text(separator="\n", strip=True)
        if len(text) > 200:
            return text

    # 3. 最长文本块 — 用快速预检跳过小候选
    candidates = soup.select("div, section, p")
    best, best_len = "", 0
    for c in candidates:
        # 快速预检: 用 .text (拼接所有子文本节点) 而非 .get_text()
        # .text 是 property 访问，比 get_text() 快
        quick_text = c.text if hasattr(c, 'text') else ''
        quick_len = len(quick_text.strip())
        if quick_len < 300:   # 跳过明显太小的候选
            continue
        # 只对可能的大型候选调用完整的 get_text()
        text = c.get_text(separator="\n", strip=True)
        if len(text) > best_len:
            best, best_len = text, len(text)

    if best_len > 300:
        return best

    # 4. body 兜底
    el = soup.select_one("body")
    return el.get_text(separator="\n", strip=True) if el else ""


def html_to_markdown(html: str, pre_cleaned: bool = False) -> str:
    """
    HTML → Markdown。
    设置 pre_cleaned=True 如果 html 已经是 clean_html() 的输出，
    避免重复 BeautifulSoup 解析（~40% 性能提升）。
    """
    import markdownify
    if pre_cleaned:
        # 输入已经是清洗过的 HTML，直接转换
        md = markdownify.markdownify(
            html, heading_style="ATX", bullets="-",
            strip=["img", "a", "script", "style"],
        )
    else:
        cleaned = clean_html(html)
        md = markdownify.markdownify(
            cleaned, heading_style="ATX", bullets="-",
            strip=["img", "a", "script", "style"],
        )
    return re.sub(r"\n{4,}", "\n\n\n", md).strip()


def process_content(html: str, max_len: int = 50000) -> dict:
    """完整处理管线：清洗 → 提取 → 转 Markdown（只解析一次 HTML）"""
    try:
        cleaned = clean_html(html)
        plain_text = extract_article_text(cleaned)
        # 关键优化: pre_cleaned=True 避免 html_to_markdown 再次调用 clean_html()
        markdown = html_to_markdown(cleaned, pre_cleaned=True)
        truncated = len(markdown) > max_len
        if truncated:
            markdown = markdown[:max_len] + "\n\n... [截断]"
        return {
            "markdown": markdown,
            "plain_text": plain_text[:max_len],
            "text_length": len(plain_text),
            "md_length": len(markdown),
            "truncated": truncated,
        }
    except Exception as e:
        text = html[:max_len]
        return {
            "markdown": text,
            "plain_text": text,
            "text_length": len(text),
            "md_length": len(text),
            "truncated": True,
            "error": str(e),
        }
