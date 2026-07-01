"""
BiliBrain 配置系统 (部署版)
==========================
加载链: ./config.json > ~/.browser-brain/config.json > 环境变量 > 默认值
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    """应用全局配置"""

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

    # ── 持久化 ────────────────────────────────────────
    sqlite_db_path: str = ""  # 空 = 使用默认路径 ~/.browser-brain/captures.db

    # ── 日志 ──────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = ""  # 空 = 仅控制台

    def __post_init__(self):
        """解析派生值"""
        if not self.sqlite_db_path:
            self.sqlite_db_path = str(
                Path.home() / ".browser-brain" / "captures.db"
            )
        if not self.outbrain_dir:
            self.outbrain_dir = str(Path.home() / "外脑")
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
    """设置全局配置"""
    global _config
    _config = cfg
