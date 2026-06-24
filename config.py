"""
Browser Brain 配置系统
=====================
加载链: ./config.json > ~/.browser-brain/config.json > 环境变量 > 默认值
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    """应用全局配置"""

    # ── Chrome / CDP ──────────────────────────────────
    chrome_port: int = 9222
    chrome_startup_timeout: float = 30.0
    chrome_poll_interval: float = 1.0
    chrome_attach_only: bool = False  # True = 仅附加，不启动

    # 浏览器发现：注册表键
    browser_registry_keys: dict = field(default_factory=lambda: {
        "chrome": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        "edge": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
        "brave": r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe",
    })

    # 浏览器回退路径（注册表失败时）
    browser_fallback_paths: dict = field(default_factory=lambda: {
        "chrome": [
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
            f"{os.environ.get('LOCALAPPDATA', '')}/Google/Chrome/Application/chrome.exe",
        ],
        "edge": [
            "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        ],
        "brave": [
            "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe",
        ],
    })

    # 各浏览器的用户数据目录模板
    browser_user_data_templates: dict = field(default_factory=lambda: {
        "chrome": "{localappdata}/Google/Chrome/User Data",
        "edge": "{localappdata}/Microsoft/Edge/User Data",
        "brave": "{localappdata}/BraveSoftware/Brave-Browser/User Data",
    })

    # 独立 profile 目录（最后手段）
    isolated_profile_dir: str = ""

    # ── CDP 捕获 ──────────────────────────────────────
    capture_max_html_bytes: int = 500_000
    capture_ws_timeout: float = 5.0
    capture_cache_ttl: int = 30  # 秒
    capture_ws_pool_max_idle: int = 60  # 秒
    capture_retry_attempts: int = 3
    capture_retry_backoff: tuple = (0.5, 1.0, 2.0)  # 秒

    # ── Flask ─────────────────────────────────────────
    flask_host: str = "127.0.0.1"
    flask_port: int = 5577

    # ── AI ────────────────────────────────────────────
    anthropic_auth_token: str = ""
    anthropic_base_url: str = "https://api.deepseek.com"
    anthropic_model: str = "deepseek-v4-flash"

    # ── 外脑知识库 ────────────────────────────────────
    outbrain_dir: str = ""  # 空 = ~/外脑 (跨平台)
    raw_clippings_subdir: str = "raw/视频与博客"
    wiki_subdir: str = "wiki"
    wiki_summary_subdir: str = "wiki/摘要"

    # ── 工具路径 ──────────────────────────────────────
    ffmpeg_path: str = ""  # 空 = 自动检测
    whisper_model_dir: str = ""  # 空 = ~/.browser-brain/whisper-models

    # ── 持久化 ────────────────────────────────────────
    sqlite_db_path: str = ""  # 空 = 使用默认路径 ~/.browser-brain/captures.db

    # ── 日志 ──────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = ""  # 空 = 仅控制台

    # ── 桌面窗口 ──────────────────────────────────────
    window_title: str = "Browser Brain"
    window_width: int = 1100
    window_height: int = 750
    window_min_width: int = 800
    window_min_height: int = 500

    def __post_init__(self):
        """解析派生值"""
        if not self.isolated_profile_dir:
            self.isolated_profile_dir = str(
                Path.home() / ".browser-brain-chrome"
            )
        if not self.sqlite_db_path:
            self.sqlite_db_path = str(
                Path.home() / ".browser-brain" / "captures.db"
            )
        if not self.outbrain_dir:
            self.outbrain_dir = str(Path.home() / "外脑")
        if not self.whisper_model_dir:
            self.whisper_model_dir = str(
                Path.home() / ".browser-brain" / "whisper-models"
            )
        # 从环境变量读取 AI 配置
        if not self.anthropic_auth_token:
            self.anthropic_auth_token = os.environ.get(
                "ANTHROPIC_AUTH_TOKEN", ""
            )
        if not self.anthropic_base_url or self.anthropic_base_url == "https://api.deepseek.com":
            self.anthropic_base_url = os.environ.get(
                "ANTHROPIC_BASE_URL", "https://api.deepseek.com"
            )
        if os.environ.get("ANTHROPIC_MODEL"):
            self.anthropic_model = os.environ["ANTHROPIC_MODEL"]
        # 去掉模型名中的上下文窗口后缀 (如 [1m]), DeepSeek API 不认
        import re as _re
        self.anthropic_model = _re.sub(r'\[\d+m\]$', '', self.anthropic_model)


def _load_json_config(path: str) -> dict:
    """加载 JSON 配置文件，不存在则返回空"""
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_config(config_path: str = None) -> AppConfig:
    """
    按优先级加载配置:
    1. 指定 config_path (./config.json)
    2. ~/.browser-brain/config.json
    3. 环境变量
    4. 默认值
    """
    # 合并所有 JSON 配置源（低优先级先）
    merged = {}

    user_config = Path.home() / ".browser-brain" / "config.json"
    merged.update(_load_json_config(str(user_config)))

    if config_path:
        merged.update(_load_json_config(config_path))
    else:
        local_config = Path("config.json")
        merged.update(_load_json_config(str(local_config)))

    # 过滤出 AppConfig 已知字段
    field_names = {f.name for f in AppConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in merged.items() if k in field_names}

    return AppConfig(**filtered)


# 全局单例
_config: AppConfig = None


def get_config() -> AppConfig:
    """获取全局配置单例"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(cfg: AppConfig):
    """设置全局配置（测试用）"""
    global _config
    _config = cfg
