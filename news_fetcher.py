"""
网页全文抓取模块 —— 当 RSS 摘要太短时，自动抓取原文正文

使用多种策略提高抓取成功率：
1. readability-lxml（标准文章页）
2. BeautifulSoup 直接提取正文区域（适合快讯/非标准页面）
3. 纯文本提取（兜底）
"""
import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup
from readability import Document

logger = logging.getLogger(__name__)

# 请求头，模拟浏览器（含更多浏览器特征）
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# 摘要太短时触发抓取的阈值（字）
SUMMARY_MIN_CHARS = 80

# 原文截取长度：传给LLM的最大字符数（原文超过此长度则截断）
MAX_FULLTEXT_CHARS = 3000

# 常见正文区域的选择器（按优先级排序）
_CONTENT_SELECTORS = [
    "article",
    "main",
    '[class*="content"]',
    '[class*="article"]',
    '[class*="post"]',
    '[class*="newsflash"]',
    '[class*="detail"]',
    '[class*="main"]',
    '[id*="content"]',
    '[id*="article"]',
    '[id*="main"]',
]

# 已知快讯类网站（非标准文章页面，需特殊处理）
_FLASH_SITES = ["36kr.com/newsflashes", "tmtpost.com", "ithome.com"]


def should_fetch_full_text(summary: str) -> bool:
    """判断是否应抓取原文。只要不是空摘要且是真实来源，都抓取以补充详细信息。"""
    if not summary:
        return True
    text_len = len(summary.strip())
    if text_len < SUMMARY_MIN_CHARS:
        return True
    if summary.count("。") <= 1:
        return True
    if text_len < 500:
        return True
    return False


def fetch_full_text(source_url: str, timeout: int = 15) -> str:
    """
    增强版原文抓取：使用多种策略备选，提高抓取成功率。
    
    对已知快讯类网站（36kr、钛媒体等）使用特殊处理。
    返回正文纯文本（截断到 MAX_FULLTEXT_CHARS），失败返回空字符串。
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

        if resp.encoding and resp.encoding.lower() != "utf-8":
            resp.encoding = resp.apparent_encoding or "utf-8"

        html = resp.text
        
        # 判断是否为快讯类网站
        is_flash = any(site in source_url for site in _FLASH_SITES)

        # 策略A：readability（适合标准文章页）
        text_a = _try_readability(html) if not is_flash else ""
        
        # 策略B：BeautifulSoup直接提取正文区域
        text_b = _try_bs4_direct(html)
        
        # 策略C（兜底）：纯文本提取全部可见文本
        text_c = _try_plain_text(html)

        # 选出最长的有效结果（>100字符才算有效）
        candidates = [t for t in [text_a, text_b, text_c] if t and len(t.strip()) > 100]
        if not candidates:
            logger.warning("[fetcher] 所有提取策略均未获取到有效正文")
            return ""

        best = max(candidates, key=len)
        best = best.strip()
        
        # 如果正文太长，截断到 MAX_FULLTEXT_CHARS
        if len(best) > MAX_FULLTEXT_CHARS:
            best = _smart_truncate(best, MAX_FULLTEXT_CHARS)

        logger.info("[fetcher] 抓取成功: %d 字符", len(best))
        return best

    except requests.Timeout:
        logger.warning("[fetcher] 抓取超时: %s", source_url[:50])
    except requests.HTTPError as e:
        logger.warning("[fetcher] HTTP错误 %s: %s", e.response.status_code, source_url[:50])
    except Exception as e:
        logger.warning("[fetcher] 抓取失败: %s", str(e)[:80])

    return ""


def _try_readability(html: str) -> str:
    """策略A：使用 readability-lxml 提取正文。适合标准文章页。"""
    try:
        doc = Document(html)
        content_html = doc.summary()
        soup = BeautifulSoup(content_html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        result = "\n".join(lines)
        if len(result) > 50:
            return result
    except Exception:
        pass
    return ""


def _try_bs4_direct(html: str) -> str:
    """策略B：用 BeautifulSoup 直接找正文区域。适合快讯/非标准页面。"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        # 移除无用标签
        for tag in soup(["script", "style", "nav", "footer", "aside", "header", "noscript"]):
            tag.decompose()
        
        # 尝试按选择器找正文区域
        for selector in _CONTENT_SELECTORS:
            try:
                elements = soup.select(selector)
                if elements:
                    texts = []
                    for el in elements:
                        t = el.get_text(separator="\n", strip=True)
                        if len(t) > 150:
                            texts.append(t)
                    if texts:
                        result = "\n".join(max(texts, key=len))
                        if len(result) > 150:
                            return result
            except Exception:
                continue
        
        # 兜底：取 body 中所有文本
        body = soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)
            lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 20]
            result = "\n".join(lines)
            if len(result) > 200:
                return result
    except Exception:
        pass
    return ""


def _try_plain_text(html: str) -> str:
    """策略C（兜底）：提取所有可见文本，去掉标签。"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 15]
        result = "\n".join(lines)
        return result
    except Exception:
        return ""


def _smart_truncate(text: str, max_chars: int) -> str:
    """智能截断：取开头(80%) + 尾部(20%) 的关键内容。"""
    first_part = text[:int(max_chars * 0.8)]
    last_period = max(
        first_part.rfind("。"), first_part.rfind("."),
        first_part.rfind("！"), first_part.rfind("？"),
        first_part.rfind("\n\n"),
    )
    if last_period > max_chars * 0.4:
        first_part = text[: last_period + 1]
    
    tail_start = max(len(text) - int(max_chars * 0.2), last_period + 1) if last_period > 0 else len(text) - int(max_chars * 0.2)
    if tail_start < len(text):
        tail = text[tail_start:].lstrip("\n")
        return first_part + "\n\n【以下为后文补充】\n" + tail[:int(max_chars * 0.2)]
    return first_part


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
