"""
桌面窗口 — pywebview (Windows 原生 Edge WebView2)
================================================
替代 PySide6 QWebEngineView，使用系统原生 WebView2。
无 Chromium GPU 兼容问题，更轻量。
降级链: pywebview → 系统浏览器
"""
import webbrowser

from config import get_config
from logger import get_logger

log = get_logger(__name__)


def open_qt_window(flask_url: str) -> bool:
    """
    打开 pywebview 桌面窗口加载 Flask 前端。
    返回 True 表示成功打开 webview 窗口，False 表示降级到浏览器。
    """
    cfg = get_config()

    try:
        import webview

        log.info("使用 pywebview (Edge WebView2) 创建桌面窗口")

        webview.create_window(
            title=cfg.window_title,
            url=flask_url,
            width=cfg.window_width,
            height=cfg.window_height,
            min_size=(cfg.window_min_width, cfg.window_min_height),
        )
        webview.start()
        return True

    except ImportError:
        log.warning("pywebview 不可用，降级到系统浏览器")
        return False
    except Exception as e:
        log.error(f"webview 窗口启动失败: {e}")
        return False


def open_browser_fallback(flask_url: str):
    """降级方案：用系统默认浏览器打开"""
    log.info(f"使用系统浏览器: {flask_url}")
    webbrowser.open(flask_url)
    print(f"  浏览器打开: {flask_url}")
    print("  按 Ctrl+C 退出")
