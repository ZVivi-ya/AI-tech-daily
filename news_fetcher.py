"""
网页全文抓取模块 —— 当 RSS 摘要太短时，自动抓取原文正文
"""
import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup
from readability import Document

logger = logging.getLogger(__name__)

# 请求头，模拟浏览器
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 摘要太短时触发抓取的阈值（字）
SUMMARY_MIN_CHARS = 80

# 原文截取长度：传给LLM的最大字符数（原文超过此长度则截断）
MAX_FULLTEXT_CHARS = 3000


def should_fetch_full_text(summary: str) -> bool:
    """判断是否应抓取原文。只要不是空摘要且是真实来源，都抓取以补充详细信息。"""
    if not summary:
        return True
    # 去掉空格后的纯文本长度
    text_len = len(summary.strip())
    # 摘要短于80字 → 必须抓取
    if text_len < SUMMARY_MIN_CHARS:
        return True
    # 摘要没有句号或多句话不完整 → 抓取补充
    if summary.count("。") <= 1:
        return True
    # RSS摘要通常只有2-3句话，深度文章建议抓取原文补充丰富细节
    if text_len < 500:
        return True
    return False


def fetch_full_text(source_url: str, timeout: int = 15) -> str:
    """
    从原文链接抓取完整正文。
    使用 readability-lxml 提取正文。
    
    返回正文纯文本，失败返回空字符串。
    """
    try:
        logger.info("[fetcher] 正在抓取原文: %s", source_url[:60])
        resp = requests.get(
            source_url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # 检测编码
        if resp.encoding and resp.encoding.lower() != "utf-8":
            resp.encoding = resp.apparent_encoding or "utf-8"

        html = resp.text

        # 使用 readability 提取正文
        doc = Document(html)
        title = doc.title()
        content_html = doc.summary()

        # 清理 HTML，提取纯文本
        soup = BeautifulSoup(content_html, "html.parser")
        # 移除脚本和样式
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

        # 清理多余空行
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        full_text = "\n".join(lines)

        logger.info("[fetcher] 抓取成功: %d 字符", len(full_text))
        return full_text

    except requests.Timeout:
        logger.warning("[fetcher] 抓取超时: %s", source_url[:50])
    except requests.HTTPError as e:
        logger.warning("[fetcher] HTTP错误 %s: %s", e.response.status_code, source_url[:50])
    except Exception as e:
        logger.warning("[fetcher] 抓取失败: %s", str(e)[:80])

    return ""


def extract_key_sections(text: str, max_chars: int = None) -> str:
    """
    从全文提取关键段落，用于 LLM 改写。
    取正文完整内容（除非超过上限则截断到 max_chars 并保留关键结尾）。
    """
    if max_chars is None:
        max_chars = MAX_FULLTEXT_CHARS
    if not text:
        return ""
    
    # 全文 <= max_chars，直接返回全部
    if len(text) <= max_chars:
        return text
    
    # 超过 max_chars：取开头(80%) + 关键信息段落(20%)
    first_part = text[:int(max_chars * 0.8)]
    # 在截断处附近找句号
    cut = int(max_chars * 0.8)
    last_period = max(
        first_part.rfind("。"), first_part.rfind("."),
        first_part.rfind("！"), first_part.rfind("？"),
        first_part.rfind("\n\n"),
    )
    if last_period > max_chars * 0.4:
        first_part = text[: last_period + 1]
    
    # 补充尾部内容（取最后 max_chars*0.2 字符内的关键信息）
    tail_start = max(len(text) - int(max_chars * 0.2), last_period + 1) if last_period > 0 else len(text) - int(max_chars * 0.2)
    if tail_start < len(text):
        tail = text[tail_start:]
        # 从尾部找段首开始
        tail = tail.lstrip("\n")
        return first_part + "\n\n【以下为后文补充】\n" + tail[:int(max_chars * 0.2)]
    
    return first_part
