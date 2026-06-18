"""
多源新闻抓取模块 —— 从多个平台获取真实新闻数据

数据源：
- RSS：36氪、少数派、InfoQ、IT之家、爱范儿、钛媒体、量子位
  TechCrunch、CNET、The Verge、WIRED
- Web Search：Bing News 搜索（补充 AI 资讯）

注：虎嗅、极客公园、机器之心 因RSS不可用/需内测，暂未接入
"""
import calendar
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import feedparser
import requests
from bs4 import BeautifulSoup

from config import Config
from news_fetcher import fetch_full_text, should_fetch_full_text, extract_key_sections

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# ========== RSS 源 ==========
RSS_SOURCES = [
    {"name": "36氪", "url": "https://36kr.com/feed"},
    {"name": "少数派", "url": "https://sspai.com/feed"},
    {"name": "InfoQ", "url": "https://www.infoq.cn/feed"},
    # 新增中文科技媒体
    {"name": "IT之家", "url": "https://www.ithome.com/rss/"},
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed"},
    {"name": "钛媒体", "url": "http://www.tmtpost.com/feed"},
    {"name": "量子位", "url": "https://www.qbitai.com/feed"},
    # 新增英文科技媒体
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
    {"name": "CNET", "url": "https://www.cnet.com/rss/news/"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
    {"name": "WIRED", "url": "https://www.wired.com/feed/rss"},
    # AI前沿研究/论文
    {"name": "arXiv AI", "url": "https://arxiv.org/rss/cs.AI"},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml"},
    # AI新闻聚合
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage"},
    {"name": "TLDR AI", "url": "https://tldr.tech/api/rss/ai"},
]

# ========== 搜索关键词（主动搜索补充 AI 新闻）==========
SEARCH_QUERIES = [
    # 大模型发布
    "new AI language model release 2026",
    "new AI model architecture breakthrough MoE transformer 2026",
    "AI model architecture innovation Loop Engineering 2026",
    # AI工具/工程
    "AI coding tool Cursor Copilot update 2026",
    "AI agent framework workflow automation tool 2026",
    "MCP protocol AI integration tool 2026",
    # AI研究突破
    "AI reasoning model open source 2026",
    "new multimodal AI model vision language 2026",
    "AI training inference optimization breakthrough 2026",
    # 中文补充
    "大模型 新架构 MoE 最新发布 2026",
    "AI编程 工具 Cursor Windsurf Claude Code 升级 2026",
    "AI自动化 工作流 Agent框架 开源 2026",
]

# AI/科技过滤关键词 — 标题匹配（必须）。只有标题命中才保留（严格模式，避免非AI内容混入）
# 注意：只保留与AI模型、AI工具、AI架构直接相关的关键词
AI_KEYWORDS_TITLE = [
    # ===== 核心大模型/架构（最高优先级） =====
    "大模型", "大语言模型", "语言模型", "基础模型", "foundation model",
    "GPT", "ChatGPT", "OpenAI", "Claude", "Gemini", "Gemma", "Llama",
    "MoE", "Transformer", "diffusion", "transformer架构", "模型架构",
    "模型发布", "开源模型", "新模型", "模型升级",
    "LLM", "多模态", "多模态模型", "推理模型", "思考模型",
    
    # ===== AI工程/架构创新 =====
    "架构创新", "架构突破", "循环工程", "Loop Engineering",
    "模型训练", "推理优化", "模型压缩", "蒸馏", "量化",
    "RAG", "Agent", "AI Agent", "智能体", "MCP", "Function Calling",
    "AI编程", "Copilot", "Cursor", "Windsurf", "Claude Code", "Codex",
    "AI自动化", "自动化工作流", "AI工具", "AI软件", "workflow",
    
    # ===== AI公司动态（仅核心AI业务） =====
    "Anthropic", "OpenAI", "Google DeepMind", "Meta AI", "xAI",
    "deepseek", "月之暗面", "智谱", "百川", "minimax",
    
    # ===== AI研究成果(严格：必须与AI直接相关) =====
    "论文", "benchmark", "SOTA", "state-of-the-art",
    "注意力机制", "注意力",
    "AIGC", "生成式AI", "AI生成", "AI创作",
    
    # ===== 与AI直接相关的应用 =====
    "AI编程", "AI代码生成", "AI对话", "AI搜索",
    "自动驾驶", "具身智能",
]

# AI/科技关键词 — 摘要补充匹配（标题未命中时，检查摘要，但要求更严格：摘要中命中2个以上才通过）
AI_KEYWORDS_SUMMARY = AI_KEYWORDS_TITLE[:]

# 合集过滤
COLLECTION_KEYWORDS = [
    "8点1氪", "氪星晚报", "晚报", "今日热点", "今日要闻",
    "一周要闻", "一周回顾", "行业周报", "盘点", "综述", "早报",
]

# 排除关键词 — 命中标题的将被剔除（与AI/科技核心资讯无关的内容）
EXCLUDE_TITLE_KEYWORDS = [
    # 低空经济/水上飞行/硬件产品（非AI）
    "水上飞行", "水上飞行器", "低空经济", "eVTOL", "飞行汽车",
    "无人机", "卫星", "火箭",
    # 游戏/娱乐（非AI技术）- 严格排除
    "游戏", "手游", "网游", "端游", "页游", "3A游戏", "主机游戏",
    "梦幻", "魔法", "公主", "玩家", "电竞", "副本", "通关", "关卡", "DLC",
    "悟空", "黑神话", "黑神话：悟空", "宝可梦", "马里奥", "塞尔达", "原神",
    "销量", "全球销量", "万份", "万套", "Steam", "TGA", "Epic Games",
    # 券商/金融研报（非AI技术）
    "证券", "券商", "研报", "涨价窗口", "涨价", "迎来涨价",
    # 纯股市/金融行情（非AI技术）
    "成交额", "沪深", "两市", "万亿", "涨停", "跌停", "A股",
    "收盘", "开盘", "股指", "指数", "板块", "领涨", "领跌",
    # 手机屏幕/硬件参数（非AI技术）
    "峰值亮度", "nits", "万级", "nit", "高亮屏", "亮度",
    "角色扮演", "皮肤", "公会",
    # 纯财经/金融（非AI，与非AI产业有关但不涉及AI技术本身）
    "REITs", "流动性", "扩容", "黄金", "白银", "期货", "股指",
    "基金", "A股", "港股", "炒股", "理财", "保险", "券商", "降息",
    "加息", "货币政策", "信贷", "债市", "外汇",
    # 股票交易/股价波动（纯金融，非AI技术）
    "盘前", "涨超", "跌幅", "跌超", "中概股", "美股", "股价",
    "收盘", "开盘", "大涨", "大跌", "止跌", "反弹", "牛市", "熊市",
    "回购", "套现", "减持", "增持", "股东", "分红",
    "牛市", "熊市", "抄底", "做多", "做空", "成交量", "换手率",
    # 体育/赛事
    "奥运", "金牌", "银牌", "奖牌", "赛事", "世界杯", "中超",
    "NBA", "CBA",
    # 房地产
    "房地产", "楼市", "房价", "土地", "房贷", "公积金",
    # 汽车（非智能驾驶/座舱核心）
    "汽车销量", "车企", "新车", " SUV", "轿车", "试驾", "测评",
    "混动", "纯电", "续航", "充电桩", "补能",
    "比亚迪", "特斯拉",
    # 纯机器人融资/量产（非AI技术突破，除非明确含AI关键词）
    "人形机器人", "双足机器人", "四足机器人", "机器人融资",
    "天使轮", "A轮融资", "B轮融资", "C轮融资",
    "累计融资", "融资数亿", "数亿美元", "成独角兽",
    # 芯片/硬件（非AI核心，除非明确指AI芯片）
    "流片", "3D堆叠", "TokenPU", "芯片发布", "芯片流片",
    # 非AI硬件发布（纯手机/耳机/穿戴设备等，不涉及AI技术本身）
    "手机曝光", "手机发布", "手机开售", "真无线", "耳夹式",
    "跑分", "开售", "预售", "售价",
    "配色", "摄像头", "像素",
    # 汽车测试/纯汽车资讯（非AI核心）
    "极速", "高环测试", "零百", "路试",
    "YU7 GT", "SU7", "问界", "启境", "启境汽车",
    # 网络安全（非AI技术本身）
    "FBI", "网络攻击", "黑客", "勒索软件", "网络入侵",
    # 地方产业/招商/政策（非AI技术内容）
    "招商", "产业园", "创新园", "孵化器", "签约", "落户",
    "高质量发展", "产业融合", "产业大会", "数字经济",
    "印发", "政策措施", "若干措施", "实施方案", "指导意见",
    # 社会现象/心理/生活方式（非AI核心）
    "多巴胺", "焦虑", "解压", "心理健康", "心理慰藉",
    # 纯硬件产品（非AI核心）
    "笔记本", "电脑", "显示器", "眼镜", "XR", "AR",
    "相机", "云台", "镜头", "传感器",
    # 游戏显卡/驱动（非AI核心）
    "DLSS", "RTX", "显卡", "驱动", "帧率", "游戏性能",
    # 系统更新（非AI核心，除非标题明确带AI）
    "系统更新", "版本更新", "性能优化", "性能提升",
    "生产力", "Bug修复", "问题修复",
    # 消费/生活
    "医美", "化妆品", "护肤", "旅游", "酒店", "美食", "穿搭",
    "奢侈品", "潮牌",
    # 能源/大宗商品
    "石油", "天然气", "煤炭", "矿", "光伏组件",
    # 材料科学/硬科技制造（非AI）
    "同位素", "碳化硅", "激光剥离", "电致变色", "导电聚合物",
    "船舶", "造船", "推进器", "永磁",
    "建筑", "绿色建筑", "装配式",
    # 航天/太空（非AI核心，除非明确提到AI技术）
    "太空", "火箭发射", "卫星互联网", "星链", "星际",
    "星座", "发射", "出征", "遥感", "航天",
    # 制造业/工业流通（非AI相关）
    "MRO", "工业用品", "工业品", "供应链", "采购",
    "出海", "海外建厂",
    # 政治/政策（非科技政策）
    "外交部", "国防", "军事",
    # IPO/市值/融资（纯金融维度，非AI技术）
    "IPO", "上市", "市值", "融资", "Pre-A", "A轮", "B轮",
    "C轮", "D轮", "种子轮", "天使轮", "募资", "估值",
    # 地产/基建
    "房地产", "楼市", "房价",
    # 医疗/健康（非AI技术，除非标题明确提到AI诊断等）
    "心脏起搏器", "起搏器", "血压", "血糖", "疫苗", "药物",
    "FDA", "医疗器械", "临床试验", "患者", "医生", "医院",
    "疾控", "传染病", "流感",
    # 科普/安全提示（无AI含量）
    "科普", "小知识", "提醒", "注意", "千万别", "别再做",
]


def fetch_all_news(hours: int = 48) -> List[Dict[str, Any]]:
    """
    从所有数据源获取新闻，返回合并后的原始列表。
    """
    all_news = []
    
    # 1. RSS 源
    all_news.extend(_fetch_rss(hours))
    
    # 2. Bing News 搜索
    try:
        bing_news = _fetch_bing_news(hours)
        all_news.extend(bing_news)
        logger.info("[rss] Bing 搜索补充 %d 条", len(bing_news))
    except Exception as e:
        logger.warning("[rss] Bing 搜索失败: %s", e)
    
    return all_news


def _fetch_rss(hours: int) -> List[Dict]:
    """从 RSS 源抓取。使用 feedparser 的 published_parsed 精确解析日期。"""
    all_news = []
    cutoff = datetime.now(CST) - timedelta(hours=hours)

    for source in RSS_SOURCES:
        try:
            logger.info("[rss] RSS: %s", source["name"])
            feed = feedparser.parse(source["url"])
            count = 0
            for entry in feed.entries:
                pub_date = _parse_date(entry)
                # 日期可解析且在时间窗口内 → 保留；日期不可解析 → 跳过（防止旧新闻混入）
                if pub_date is None:
                    continue
                if pub_date < cutoff:
                    continue
                news = {
                    "title": entry.get("title", ""),
                    "summary": _clean_html(entry.get("summary", entry.get("description", ""))),
                    "source_url": entry.get("link", ""),
                    "source_name": source["name"],
                    "published_at": _format_published(pub_date),
                }
                # 处理 arXiv 特殊格式：去掉 "Title: " 和 "Abstract: " 前缀
                if source["name"] == "arXiv AI":
                    if news["title"].startswith("Title: "):
                        news["title"] = news["title"][7:]
                    summary = news["summary"]
                    if summary.startswith("Abstract:"):
                        summary = summary[9:]
                    elif "Abstract:" in summary:
                        summary = summary.split("Abstract:", 1)[1]
                    news["summary"] = summary.strip()
                all_news.append(news)
                count += 1
            logger.info("[rss] %s 抓取 %d 条", source["name"], count)
        except Exception as e:
            logger.warning("[rss] %s 失败: %s", source["name"], e)

    return all_news


def _fetch_bing_news(hours: int) -> List[Dict]:
    """
    通过 Bing News 搜索（Bing 网页搜索），获取 AI 科技新闻。
    这里不调用付费 API，而是直接请求 Bing News 搜索。
    """
    all_news = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    seen_urls = set()
    
    for query in SEARCH_QUERIES:
        try:
            url = f"https://www.bing.com/news/search?q={requests.utils.quote(query)}&setlang=zh-Hans"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("a.title") or soup.select(".news-card a")

            for card in cards[:10]:
                title = card.get_text(strip=True)
                href = card.get("href", "")
                if not href or not title:
                    continue
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                news = {
                    "title": title,
                    "summary": "",  # Bing 搜索摘要太短，后续会抓取原文
                    "source_url": href,
                    "source_name": "Bing News",
                    "published_at": "",  # Bing 搜索结果无发布时间，留空避免编造
                }
                all_news.append(news)

        except Exception as e:
            logger.warning("[rss] Bing 搜索 '%s' 失败: %s", query[:20], str(e)[:50])
            continue

    return all_news


def filter_ai_news(news_list: List[Dict]) -> List[Dict]:
    """过滤 AI 相关 + 跳过合集 + 排除无关话题，并自动抓取原文补充摘要。

    过滤策略（两层）：
    - 标题命中 AI_KEYWORDS_TITLE → 直接通过
    - 标题未命中但摘要命中 2+ 个 AI_KEYWORDS_SUMMARY → 通过（宽松补充）
    - 否则 → 跳过
    """
    filtered = []
    for n in news_list:
        title = n["title"]

        # 跳过合集/综述
        if any(kw in title for kw in COLLECTION_KEYWORDS):
            continue

        # 排除无关话题（标题命中即跳过）
        if any(kw.lower() in title.lower() for kw in EXCLUDE_TITLE_KEYWORDS):
            continue

        # 严格两层 AI 关键词过滤
        title_text = title
        summary_text = n.get("summary", "")

        # 第一层：标题匹配
        title_match = any(kw.lower() in title_text.lower() for kw in AI_KEYWORDS_TITLE)
        if title_match:
            # 标题已匹配，直接通过
            pass
        else:
            # 第二层：摘要必须命中 2+ 个 AI 关键词
            summary_hits = sum(1 for kw in AI_KEYWORDS_SUMMARY if kw.lower() in summary_text.lower())
            if summary_hits < 2:
                continue

        # 如果摘要太短，尝试抓取原文
        summary = n.get("summary", "")
        if should_fetch_full_text(summary):
            full_text = fetch_full_text(n["source_url"])
            if full_text:
                n["summary"] = extract_key_sections(full_text)

        filtered.append(n)

    # 去重
    return _deduplicate(filtered)


def _parse_date(entry) -> datetime:
    """使用 feedparser 的 published_parsed 精确解析日期，支持所有时区和格式。

    返回 CST (UTC+8) 时区的 datetime，解析失败返回 None。
    """
    try:
        tp = entry.get("published_parsed")
        if tp:
            # published_parsed 是 UTC 时间，用 calendar.timegm 正确转换
            utc_dt = datetime.fromtimestamp(calendar.timegm(tp), tz=timezone.utc)
            return utc_dt.astimezone(CST)
    except Exception:
        pass
    # 回退：尝试常见日期格式
    try:
        date_str = entry.get("published", "").strip()
        if not date_str:
            return None
        return _parse_date_str(date_str)
    except Exception:
        return None


def _parse_date_str(date_str: str) -> datetime:
    """解析多种日期格式，返回 CST 时区的 datetime。

    只解析包含具体时间的日期（如 "... 12:30:00 ..."），
    纯日期（如 "2026-06-08"）不返回时间，避免编造 00:00。
    返回 None 表示无法解析。
    """
    # 统一处理
    cleaned = re.sub(r"\s*[+-]\d{4}\s*$", "", date_str)
    cleaned = re.sub(r"\s*(UTC|GMT|CST)\s*$", "", cleaned, flags=re.IGNORECASE).strip()

    # 尝试各种标准格式（必须包含时间）
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%a, %d %b %Y %H:%M:%S",       # RFC 2822 无时区
        "%d %b %Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned[:len(fmt)], fmt)
            # 无时区信息，视为 UTC
            return dt.replace(tzinfo=timezone.utc).astimezone(CST)
        except ValueError:
            continue

    # 纯日期格式（无时间）→ 返回 None，不编造 00:00
    try:
        datetime.strptime(cleaned[:10], "%Y-%m-%d")
        # 只有日期没时间 → 返回 None，让 caller 决定是否使用
        return None
    except ValueError:
        pass

    return None


def _format_published(dt: datetime) -> str:
    """格式化发布时间。防止时区转换导致未来日期（UTC晚于16:00→CST次日）。"""
    if dt is None:
        return ""
    now_cst = datetime.now(CST)
    # 如果转换后的日期 > 今天 -> 显示"今天"
    if dt.date() > now_cst.date():
        if dt.minute == 0:
            return now_cst.strftime("%Y-%m-%d")
        return now_cst.strftime("%Y-%m-%d %H:%M")
    # 整点时间（如 04:00, 08:00, 00:00）→ 只显示日期
    if dt.minute == 0:
        return dt.strftime("%Y-%m-%d")
    # 有具体分钟信息 → 显示完整时间
    return dt.strftime("%Y-%m-%d %H:%M")


def _clean_html(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def _deduplicate(news_list: List[Dict]) -> List[Dict]:
    seen = set()
    result = []
    for n in news_list:
        key = n["title"][:30]
        if key not in seen:
            seen.add(key)
            result.append(n)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raw = fetch_all_news()
    print(f"原始条数: {len(raw)}")
    fil = filter_ai_news(raw)
    print(f"过滤后: {len(fil)}")
    for i, n in enumerate(fil[:8]):
        slen = len(n.get("summary", ""))
        print(f"\n{i+1}. [{n['source_name']}] {n['title'][:50]}")
        print(f"   摘要长度: {slen}字")
