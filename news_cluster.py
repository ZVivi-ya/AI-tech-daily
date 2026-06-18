"""
事件聚类模块 —— 将多个来源的同一事件合并为一条新闻
"""
import logging
import re
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# ─── 来源权威评分字典 ───
# 用于聚类合并时选择主来源（分数越高越权威）
# 不在字典中的来源默认给 50 分
SOURCE_SCORES = {
    "量子位": 92,
    "InfoQ": 91,
    "36氪": 88,
    "IT之家": 82,
    "爱范儿": 79,
    "钛媒体": 78,
    "Hugging Face Blog": 76,
    "少数派": 74,
    "arXiv AI": 73,
    "TechCrunch": 69,
    "Hacker News": 54,
    "TLDR AI": 52,
}


def _source_score(source_name: str) -> int:
    """查来源权威评分，未收录来源默认 50 分。"""
    return SOURCE_SCORES.get(source_name, 50)


def cluster_events(news_list: List[Dict]) -> List[Dict]:
    """
    将多源新闻按事件聚类合并。
    
    输入：来自不同源的原始新闻（含 title, summary, source_url, source_name）
    输出：合并后的新闻列表，同一事件的多个来源合并为一条
    
    合并策略：
    - 标题相似度（关键词交集）判断是否为同一事件
    - 同一事件的 news 合并到 combined_sources 中
    - 多源摘要拼接：所有来源的摘要内容合并为一个综合性文本（标注来源）
    """
    if not news_list:
        return []

    # Step 1: 提取每篇新闻的关键词
    enriched = []
    for n in news_list:
        keywords = _extract_keywords(n["title"])
        enriched.append({**n, "_keywords": set(keywords)})

    # Step 2: 聚类（阈值比原来更低，更容易合并）
    clusters = []  # 每个 cluster 是 index 列表
    used = set()

    for i, item in enumerate(enriched):
        if i in used:
            continue

        cluster = [i]
        used.add(i)
        ki = item["_keywords"]
        title1 = item["title"]

        for j in range(i + 1, len(enriched)):
            if j in used:
                continue
            item_j = enriched[j]
            kj = item_j["_keywords"]

            # 跳过空关键词
            if len(ki) == 0 or len(kj) == 0:
                continue

            overlap = len(ki & kj)

            # 策略A：Jaccard 相似度（交/并）
            sim_jaccard = overlap / len(ki | kj) if len(ki | kj) > 0 else 0
            # 策略B：重叠占短列表比例
            sim_min = overlap / min(len(ki), len(kj)) if min(len(ki), len(kj)) > 0 else 0
            # 策略C：标题字符级交集比例（同一事件的不同表述）
            chars_i = set(re.findall(r"[\w\u4e00-\u9fff]+", title1))
            chars_j = set(re.findall(r"[\w\u4e00-\u9fff]+", item_j["title"]))
            char_overlap = len(chars_i & chars_j)
            char_sim = char_overlap / min(len(chars_i), len(chars_j)) if chars_i and chars_j else 0

            # 任一策略达标即视为同一事件（阈值调低，更容易合并）
            if sim_jaccard >= 0.15 or sim_min >= 0.20 or char_sim >= 0.35:
                cluster.append(j)
                used.add(j)

        clusters.append(cluster)

    # Step 3: 多源合并
    merged = []
    for cluster_indices in clusters:
        items = [enriched[i] for i in cluster_indices]

        # 取来源权威评分最高的作为主条目，分数相同则选标题更长的
        main_item = max(items, key=lambda x: (_source_score(x.get("source_name", "")), len(x["title"])))

        # 收集所有来源信息（包括完整摘要）
        sources = []
        for item in items:
            sources.append({
                "source_name": item.get("source_name", ""),
                "source_url": item.get("source_url", ""),
                "published_at": item.get("published_at", ""),
                "summary": item.get("summary", ""),  # 保存摘要内容
            })

        # 去重来源（按URL去重）
        seen_urls = set()
        unique_sources = []
        for s in sources:
            url = s["source_url"]
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_sources.append(s)

        # === 多源摘要拼接：把多个来源的内容合并为一个综合性文本 ===
        if len(unique_sources) > 1:
            merged_parts = []
            for idx, s in enumerate(unique_sources):
                label = f"【来源{idx+1}: {s['source_name']}】"
                content = s.get("summary", "").strip()
                if content:
                    merged_parts.append(f"{label}\n{content}")
            merged_summary = "\n\n".join(merged_parts)
        else:
            # 单源时取最长的那篇
            merged_summary = max((item.get("summary", "") for item in items), key=len)

        # 选择主来源（来源权威评分最高的；分数相同则保留第一个）
        primary = max(unique_sources, key=lambda s: _source_score(s.get("source_name", ""))) if unique_sources else {}

        result = {
            "title": main_item["title"],
            "summary": merged_summary,  # 多源拼接后的摘要
            "company": main_item.get("company", ""),
            "source_url": primary.get("source_url", ""),
            "source_name": primary.get("source_name", ""),
            "published_at": main_item.get("published_at", ""),
            "combined_sources": unique_sources,  # 保存所有来源（含摘要），供后续改写使用
            "is_multi_source": len(unique_sources) > 1,  # 标记是否多源
        }
        merged.append(result)

    logger.info("[cluster] %d 条新闻聚类为 %d 个事件", len(news_list), len(merged))
    return merged


def _extract_keywords(text: str) -> List[str]:
    """从标题中提取关键实体词（公司名、产品名、核心动词）。"""
    # 中文科技新闻常见的关键词模式
    # 提取：中文字词、英文单词、数字（各自独立）
    # 注：[\w\u4e00-\u9fff]+ 会把 "5遭白宫" 等中英数字混写吞成一个 token，
    #     导致中文关键词因 token 以数字开头而被 eng/cn 筛选丢弃。
    #     改用分组表达式确保不同字符类各自独立匹配。
    words = re.findall(r"[a-zA-Z]+|[0-9]+|[\u4e00-\u9fff]+", text)

    # 过滤停用词（只保留真正的虚词）
    STOP_WORDS = {"的", "了", "在", "是", "与", "和", "或", "有",
                   "这", "那", "之", "中", "上", "下", "以", "而"}

    # 保留有意义的词（长度 >= 2 且不是停用词）
    keywords = [w for w in words if len(w) >= 2 and w not in STOP_WORDS]

    # 优先保留英文词（如 MiMo Code, OpenAI, Claude 等）
    eng_words = [w for w in keywords if re.match(r"^[a-zA-Z]", w)]
    cn_words = [w for w in keywords if re.match(r"^[\u4e00-\u9fff]", w)]

    result = eng_words + cn_words
    return result[:8]  # 最多取8个关键词
