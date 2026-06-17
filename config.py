"""
配置管理模块 —— 从 .env 文件读取并校验所有配置项
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件（支持多层级向上查找）
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)


class Config:
    # ─── DeepS API ───
    DEEPS_API_KEY: str = os.getenv("DEEPS_API_KEY", "")
    DEEPS_BASE_URL: str = os.getenv("DEEPS_BASE_URL", "https://api.deepseek.com/v1")

    # ─── 微信公众号 ───
    WX_APPID: str = os.getenv("WX_APPID", "")
    WX_APPSECRET: str = os.getenv("WX_APPSECRET", "")
    THUMB_MEDIA_ID: str = os.getenv("THUMB_MEDIA_ID", "") or ""

    # ─── 项目路径 ───
    PROJECT_ROOT: Path = Path(__file__).parent
    HTML_OUTPUT_DIR: Path = PROJECT_ROOT / "output"


# 项目级校验
_CRITICAL_KEYS = ["DEEPS_API_KEY"]
for key in _CRITICAL_KEYS:
    if not getattr(Config, key, ""):
        raise RuntimeError(
            f"[config] 缺少必要配置项 {key}，请检查 .env 文件"
        )

# 确保输出目录存在
Config.HTML_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
