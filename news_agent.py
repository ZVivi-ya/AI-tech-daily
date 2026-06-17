"""
新闻改写模块 —— 基于多源真实数据，LLM 融合改写为深度描述
"""
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

import httpx
from openai import OpenAI

from config import Config

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

REWRITE_SYSTEM_PROMPT = """你是AI科技资讯编辑，将新闻改写成精简中文摘要。

===== 数量要求 =====
输出至少12条，最多25条。如果没有足够的AI新闻，宁可用短讯也要凑够12条。

===== 内容质量 =====
1. **保留吸引人的细节**：摘要不能只罗列标题要点，要包含具体数字（金额、时间、比例等）、有趣的事实，让读者觉得"这条有收获"。
2. **title格式**：以【公司/主题】开头，如"【字节跳动】 调整AI重心：豆包日亏千万，转向企业服务"
3. **摘要150-250字**：提炼核心+关键数据，要包含有意思的细节。不要复制原文。不要用"我们""您"。
4. **必须中文**：英文标题/内容必须翻译，不能保留英文。
5. **必须重写**：不能用原文。检测到原文复制视为不合格。

===== 必须包含字段（每项都要有）=====
{ title, summary, company, source_url, source_name, published_at }
source_url和source_name必须使用原始值，不能留空。如果不知道，用原文提供的。

===== 示例 =====
输入：{"title": "微软探索用DeepSeek替代昂贵模型", "summary": "微软...", "source_url": "https://ithome.com/...", "source_name": "IT之家"}
输出：{"title": "【微软】 考虑用DeepSeek替代Anthropic和OpenAI，降低智能体成本", "summary": "微软正将Copilot智能体转为按使用量计费，并探索用DeepSeek V4替代Anthropic和OpenAI。Anthropic Fable 5输出定价50美元/百万token，DeepSeek V4 Pro仅0.87美元，价差约57倍。", "company": "微软", "source_url": "https://ithome.com/...", "source_name": "IT之家", "published_at": "原值"}

===== 丢弃规则（仅在数量已够12条时才丢弃）=====
招商新闻、纯硬件发布、系统更新、游戏、金融行情"""



def rewrite_news(news_list: List[Dict[str, Any]], max_retries: int = 2) -> List[Dict[str, Any]]:
    """
    将新闻列表传给 LLM 改写排版。

    支持多源信息融合：如果新闻包含 combined_sources 字段，
    会将多个来源的链接和摘要一并传给 LLM。
    """
    if not news_list:
        return []

    # 构造 user prompt，传入每条新闻的详细信息
    news_data = []
    for n in news_list:
        combined = n.get("combined_sources", [])
        is_multi = n.get("is_multi_source", False) or len(combined) > 1

        entry = {
            "title": n.get("title", ""),
            "summary": n.get("summary", ""),
            "source_name": n.get("source_name", ""),
            "source_url": n.get("source_url", ""),
            "published_at": n.get("published_at", ""),
            "此事件有多个来源报道": is_multi,
        }

        if is_multi:
            # 多源时：把每个来源的完整摘要内容都附上，让LLM真正融合
            extra_sources = []
            for s in combined:
                if s.get("source_url") != n.get("source_url"):
                    src_name = s.get("source_name", "未知来源")
                    src_summary = s.get("summary", "").strip()
                    if src_summary:
                        extra_sources.append({
                            "来源": src_name,
                            "原文链接": s.get("source_url", ""),
                            "原文摘要": src_summary[:2000],  # 传摘要内容，截断避免token爆炸
                        })
                    else:
                        extra_sources.append({
                            "来源": src_name,
                            "原文链接": s.get("source_url", ""),
                        })
            if extra_sources:
                entry["其他来源报道"] = extra_sources

        news_data.append(entry)

    news_json = json.dumps(news_data, ensure_ascii=False, indent=2)
    now = datetime.now(CST)
    today_str = f"{now.year}年{now.month}月{now.day}日"

    user_prompt = f"""今天是 {today_str}。

以下是从多个来源获取的 {len(news_list)} 条真实新闻数据（每条含标题、摘要、来源）。
摘要部分已抓取**文章完整原文**（详细的技术参数、产品名称、版本号、发布时间、公司背景等都在其中）。

请将它们按深度科技短讯风格改写，输出 JSON 数组。

改写规则：
1. **输出至少12条**，最多25条。宁用短讯也要凑够12条。
2. **每条必须有source_url和source_name**，用原始值，不能留空。
3. **保留有意思的细节**：用具体数字、事实让读者觉得有收获。不要只列干条条。
4. **title格式**：以【公司/主题】开头，如"【微软】 考虑用DeepSeek V4替代Anthropic和OpenAI"
5. **必须中文**：英文全部翻译。必须重写，不能复制原文。
6. 严禁编造、published_at无时间不写时间

原始新闻数据：
{news_json}"""

    http_client = httpx.Client(proxies=None, verify=True, timeout=httpx.Timeout(180.0))
    client = OpenAI(
        api_key=Config.DEEPS_API_KEY,
        base_url=Config.DEEPS_BASE_URL,
        http_client=http_client,
    )

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info("[rewrite] 第 %d 次尝试改写 %d 条新闻 ...", attempt, len(news_list))
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.6,
                max_tokens=16384,
            )

            raw = resp.choices[0].message.content
            if not raw:
                raise ValueError("API 返回为空")

            logger.info("[rewrite] 响应: %s ...", raw[:200])
            rewritten = _parse_response(raw)
            if rewritten:
                logger.info("[rewrite] 改写成功 %d 条", len(rewritten))
                return rewritten

            raise ValueError("解析返回为空")

        except Exception as e:
            last_error = e
            logger.warning("[rewrite] 第 %d 次失败: %s", attempt, str(e)[:100])

    # 回退
    logger.warning("[rewrite] LLM 改写失败，使用原始数据")
    return _fallback(news_list)


def _parse_response(raw: str) -> List[Dict]:
    """解析 LLM 返回的 JSON。"""
    raw = raw.strip()
    if raw.startswith("```"):
        first_nl = raw.find("\n")
        if first_nl != -1:
            raw = raw[first_nl + 1:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return _normalize(data)
    except json.JSONDecodeError:
        pass

    # 尝试找 JSON 数组
    m = re.search(r"\[\s*\{", raw)
    if m:
        start = m.start()
        depth = 0
        end = -1
        for i in range(start, len(raw)):
            if raw[i] == "[":
                depth += 1
            elif raw[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end != -1:
            try:
                data = json.loads(raw[start:end])
                if isinstance(data, list):
                    return _normalize(data)
            except:
                pass
    return []


def _normalize(data: list) -> List[Dict]:
    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        result.append({
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "company": item.get("company", ""),
            "source_url": item.get("source_url", ""),
            "source_name": item.get("source_name", ""),
            "published_at": item.get("published_at", ""),
        })
    return result


def _fallback(news_list: List[Dict]) -> List[Dict]:
    result = []
    for n in news_list:
        result.append({
            "title": n.get("title", ""),
            "summary": n.get("summary", ""),
            "company": n.get("company", ""),
            "source_url": n.get("source_url", ""),
            "source_name": n.get("source_name", ""),
            "published_at": n.get("published_at", ""),
        })
    return result
