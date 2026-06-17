"""
微信公众号 API 封装 —— access_token 管理 & 创建图文草稿
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from config import Config
from formatter import build_wechat_html

logger = logging.getLogger(__name__)

# ─── Token 缓存文件 ───
TOKEN_CACHE_PATH = Config.PROJECT_ROOT / ".access_token_cache.json"

# ─── API 端点 ───
TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
DRAFT_ADD_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"
DRAFT_GET_URL = "https://api.weixin.qq.com/cgi-bin/draft/get"
DRAFT_LIST_URL = "https://api.weixin.qq.com/cgi-bin/draft/batchget"


# ═══════════════════════════════════════════
#  Access Token 管理
# ═══════════════════════════════════════════

def _load_cached_token() -> Optional[dict]:
    """从本地缓存读取 access_token（带过期检查）。"""
    if not TOKEN_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
        if data.get("expires_at", 0) > time.time() + 60:
            return data
        logger.info("[wechat] 缓存 token 已过期，将重新获取")
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[wechat] 读取 token 缓存失败: %s", e)
    return None


def _save_token_cache(token_data: dict):
    """将 access_token 写入本地缓存。"""
    TOKEN_CACHE_PATH.write_text(
        json.dumps(token_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("[wechat] token 已缓存至 %s", TOKEN_CACHE_PATH)


def get_access_token() -> str:
    """
    获取微信公众号 access_token。
    优先使用缓存，失效则向微信服务器请求新的。
    """
    cached = _load_cached_token()
    if cached:
        return cached["access_token"]

    params = {
        "grant_type": "client_credential",
        "appid": Config.WX_APPID,
        "secret": Config.WX_APPSECRET,
    }
    resp = requests.get(TOKEN_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        raise RuntimeError(
            f"获取 access_token 失败: {data.get('errmsg', '未知错误')} "
            f"(errcode={data.get('errcode', '?')})"
        )

    token_data = {
        "access_token": data["access_token"],
        "expires_at": time.time() + data.get("expires_in", 7200),
    }
    _save_token_cache(token_data)
    return token_data["access_token"]


def clear_token_cache():
    """清除本地 access_token 缓存（手动调用）。"""
    if TOKEN_CACHE_PATH.exists():
        TOKEN_CACHE_PATH.unlink()
        logger.info("[wechat] token 缓存已清除")


# ═══════════════════════════════════════════
#  草稿管理
# ═══════════════════════════════════════════

def create_draft(title: str, body_html: str) -> Dict[str, Any]:
    """
    创建微信公众号图文草稿。

    参数：
        title:     图文标题（如 "AI科技早报 · 2026年06月10日"）
        body_html: 图文正文 HTML

    返回：
        微信 API 响应（含 media_id）
    """
    access_token = get_access_token()

    # 构建图文草稿 payload
    payload = {
        "articles": [
            {
                "title": title,
                "content": body_html,
                "digest": "",        # 可选摘要，留空微信会自动取正文前 54 字
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }
        ]
    }

    # 如果有封面图 media_id，添加到第一篇文章
    if Config.THUMB_MEDIA_ID:
        payload["articles"][0]["thumb_media_id"] = Config.THUMB_MEDIA_ID

    url = f"{DRAFT_ADD_URL}?access_token={access_token}"
    # 关键：手动序列化，ensure_ascii=False 防止中文被转义为 \uXXXX
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = requests.post(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    if result.get("errcode", 0) != 0:
        raise RuntimeError(
            f"创建草稿失败: {result.get('errmsg', '未知错误')} "
            f"(errcode={result.get('errcode', '?')})"
        )

    media_id = result.get("media_id", "")
    logger.info("[wechat] 草稿创建成功！media_id: %s", media_id)
    return result


def create_news_draft(news_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    快捷函数：根据新闻列表生成 HTML 并创建微信图文草稿。
    返回微信 API 完整响应。
    """
    now = datetime.now()
    title = "AI科技早报 · {0}年{1}月{2}日".format(now.year, now.month, now.day)
    body_html = build_wechat_html(news_list)
    return create_draft(title, body_html)
