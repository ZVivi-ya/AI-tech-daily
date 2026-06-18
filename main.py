"""
AI科技早报 · 主入口

用法：
    python main.py              # 完整流程：抓新闻 → 创建微信草稿
    python main.py --preview    # 仅生成本地预览 HTML（不调微信 API）
    python main.py --test-wx    # 使用模拟新闻测试微信草稿接口

环境变量：
    请先在 .env 文件中配置 DEEPS_API_KEY、WX_APPID、WX_APPSECRET
"""
import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set

# ─── 日志配置 ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

# ─── 待确认草稿缓存文件 ───
_PENDING_DRAFT_FILE: Path = Path(__file__).parent / ".pending_draft.json"


def _load_pending_draft() -> dict:
    """从缓存文件加载待确认草稿信息。"""
    if _PENDING_DRAFT_FILE.exists():
        try:
            return json.loads(_PENDING_DRAFT_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_pending_draft(data: dict):
    """保存待确认草稿信息到缓存文件。"""
    _PENDING_DRAFT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _clear_pending_draft():
    """清除待确认草稿缓存文件。"""
    if _PENDING_DRAFT_FILE.exists():
        try:
            _PENDING_DRAFT_FILE.unlink()
        except OSError:
            pass


# ─── 已发布历史记录 ───
PUBLISHED_HISTORY_FILE: Path = Path(__file__).parent / ".published_history.json"

# URL 模式 → 文章ID提取（跨utm参数去重）
_ARTICLE_URL_PATTERNS = [
    (r"36kr\.com/newsflashes/(\w+)", 0),       # 36氪: 3850885678306561
    (r"sspai\.com/post/(\w+)", 0),              # 少数派: 110914
    (r"infoq\.cn/article/(\w+)", 0),            # InfoQ: GJsQtsz9gvhRZtXg2Wav
    (r"infoq\.cn/video/(\w+)", 0),              # InfoQ视频: 7LNG31pHhuTxEptTLMsD
    (r"openai\.com", "openai"),                  # OpenAI
    (r"blog\.google", "google"),                 # Google
    (r"nvidia\.com", "nvidia"),                  # NVIDIA
    (r"apple\.com", "apple"),                    # Apple
    (r"anthropic\.com", "anthropic"),            # Anthropic
    (r"microsoft\.com", "microsoft"),            # Microsoft
    (r"deepseek\.com", "deepseek"),              # DeepSeek
    (r"tongyi\.aliyun\.com", "aliyun"),          # 阿里云
    (r"hunyuandamodel\.tencent\.com", "tencent"), # 腾讯混元
    (r"xiaomi\.com", "xiaomi"),                  # 小米
    (r"tesla\.com", "tesla"),                    # Tesla
]


def _extract_article_id(url: str) -> str:
    """从URL提取文章唯一ID，忽略utm等查询参数。"""
    if not url:
        return ""
    for pattern, group in _ARTICLE_URL_PATTERNS:
        m = re.search(pattern, url)
        if m:
            if group == 0:
                return m.group(1)
            return str(group)
    # 回退：取URL路径最后一部分
    m = re.search(r"/([^/]+?)(?:\?|$)", url)
    if m:
        return m.group(1)
    return url


def _load_published_history() -> Set[str]:
    """加载之前已发布过的新闻文章ID集合（用于去重）。"""
    if PUBLISHED_HISTORY_FILE.exists():
        try:
            data = json.loads(PUBLISHED_HISTORY_FILE.read_text("utf-8"))
            ids = set(data.get("article_ids", []))
            logger.info("[历史] 已加载 %d 条已发布记录", len(ids))
            return ids
        except (json.JSONDecodeError, KeyError):
            logger.warning("[历史] 历史文件损坏，重新创建")
    return set()


def _save_published_history(news_list: List[Dict]):
    """保存本次发布的所有新闻的文章ID和最近7天完整信息到历史记录文件。"""
    existing = _load_published_history()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    for n in news_list:
        url = n.get("source_url", "")
        aid = _extract_article_id(url)
        if aid:
            existing.add(aid)

    # 加载已有完整记录，追加本次新发布的完整新闻（含标题/摘要/公司/日期）
    old_data = {}
    if PUBLISHED_HISTORY_FILE.exists():
        try:
            old_data = json.loads(PUBLISHED_HISTORY_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, KeyError, OSError):
            old_data = {}

    recent = old_data.get("recent_news", [])
    for n in news_list:
        recent.append({
            "title": n.get("title", ""),
            "summary": n.get("summary", ""),
            "company": n.get("company", ""),
            "published_at": n.get("published_at", today),
            "source_url": n.get("source_url", ""),
            "source_name": n.get("source_name", ""),
        })

    # 仅保留最近7天的完整记录，防止文件膨胀
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [r for r in recent if r.get("published_at", "")[:10] >= cutoff]

    data = {
        "article_ids": sorted(existing),
        "recent_news": recent,
        "last_updated": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    PUBLISHED_HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    logger.info("[历史] 已保存 %d 条历史记录", len(existing))


def _filter_published(news_list: List[Dict], published_ids: Set[str]) -> List[Dict]:
    """剔除已发布过的新闻（按文章ID去重）。"""
    filtered = []
    removed = 0
    for n in news_list:
        url = n.get("source_url", "")
        aid = _extract_article_id(url)
        if aid and aid in published_ids:
            removed += 1
            continue
        filtered.append(n)
    if removed > 0:
        logger.info("[历史] 剔除 %d 条已发布过的新闻（含标题: %s）",
                     removed, [n.get("title","")[:20] for n in news_list if _extract_article_id(n.get("source_url","")) in published_ids])
    return filtered


def load_recent_published(days: int = 2) -> List[Dict]:
    """加载最近 N 天内已发布的新闻完整信息（标题、摘要、公司名、发布日期）。

    从 .published_history.json 的 recent_news 数组中读取，
    按 published_at 筛选最近 N 天。文件不存在或格式不兼容时返回空列表。

    Args:
        days: 回溯天数，默认 2 天

    Returns:
        [{title, summary, company, published_at, source_url, source_name}, ...]
    """
    if not PUBLISHED_HISTORY_FILE.exists():
        return []

    try:
        data = json.loads(PUBLISHED_HISTORY_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("[历史] 历史文件无法解析，load_recent_published 返回空")
        return []

    recent = data.get("recent_news", [])
    if not recent:
        return []

    now = datetime.now()
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    result = []
    for item in recent:
        pub = item.get("published_at", "")
        if pub[:10] >= cutoff:
            result.append({
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "company": item.get("company", ""),
                "published_at": pub[:10],          # 只保留日期部分
                "source_url": item.get("source_url", ""),
                "source_name": item.get("source_name", ""),
            })

    logger.info("[历史] load_recent_published(days=%d): %d 条", days, len(result))
    return result


# ─── 事件追踪标记 ───

# 常见事件关键词，用于从历史标题中提取2-4字事件名
_TRACKING_EVENT_KEYWORDS = [
    "收购", "下架", "融资", "上线", "开源", "起诉", "裁员",
    "人事", "监管", "调查", "产品", "合作", "投资", "上市", "召回",
    "漏洞", "攻击", "演示", "预览", "更新", "推出", "发布",
    "合并", "拆分", "关停", "封禁", "禁令", "罚款", "获批",
    "警告", "谈判", "和解",
]


def _lcs_length(a: str, b: str) -> int:
    """计算两个字符串的最长公共子序列长度（动态规划，空间优化为 O(min(m,n))）。"""
    if not a or not b:
        return 0
    # 确保 a 是较短的
    if len(a) > len(b):
        a, b = b, a
    m, n = len(a), len(b)
    prev = [0] * (m + 1)
    for j in range(1, n + 1):
        curr = [0] * (m + 1)
        for i in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                curr[i] = prev[i - 1] + 1
            else:
                curr[i] = max(prev[i], curr[i - 1])
        prev = curr
    return prev[m]


def _title_similarity(text1: str, text2: str) -> float:
    """计算两个新闻标题的相似度。

    使用最长公共子序列 (LCS) 归一化：LCS 长度 / 两标题平均长度。
    该指标适合"同一事件不同角度"的标题对——前半共用公司名+产品名，
    后半不同细节时仍能给出合理分数。
    """
    if not text1 or not text2:
        return 0.0
    lcs = _lcs_length(text1, text2)
    avg_len = (len(text1) + len(text2)) / 2.0
    return lcs / avg_len if avg_len > 0 else 0.0


def _extract_event_keyword(history_title: str) -> str:
    """从历史标题中提取2-3字事件关键词。

    优先匹配内置事件关键词列表；未命中时取标题后半段较长的2字片段。
    """
    for kw in _TRACKING_EVENT_KEYWORDS:
        if kw in history_title:
            return kw
    # 回退：取标题末尾区域中第一个非标点的2字片段
    # 去除常见标点后切2字窗口
    clean = history_title.replace("：", "").replace("，", "").replace(" ", "")
    # 从后往前扫，找一个像事件关键词的2-3字片段
    for i in range(len(clean) - 1, 1, -1):
        seg = clean[i - 2:i + 1]  # 3-gram
        if len(seg) >= 2:
            return seg[:3]
    return "事件"


def mark_tracking_news(news_list: List[Dict],
                       recent_history: List[Dict]) -> List[Dict]:
    """对每条新闻检查是否与近期历史中的事件重复，并在原地标记追踪信息。

    检查逻辑：
    1. company 字段与历史记录中的某条一致（忽略大小写）
    2. 标题关键词重叠度 > 60%（基于 tokenize 后的集合交集/较小集）

    匹配成功后为该条新闻新增两个字段：
    - is_tracking: bool
    - tracking_title: "【追踪·{事件名}】{原标题}"
    未匹配时：is_tracking=False，不添加 tracking_title。

    Args:
        news_list: 当前待发布的新闻列表（原地修改）
        recent_history: load_recent_published 的输出结果

    Returns:
        修改后的 news_list（与原列表同一个对象）
    """
    if not recent_history:
        logger.info("[追踪] recent_history 为空，跳过标记")
        for n in news_list:
            n["is_tracking"] = False
        return news_list

    tracking_count = 0
    for news in news_list:
        company = (news.get("company", "") or "").strip().lower()
        title = (news.get("title", "") or "").strip()

        if not company:
            news["is_tracking"] = False
            continue

        matched = False
        event_name = "事件"

        for hist in recent_history:
            hist_company = (hist.get("company", "") or "").strip().lower()
            hist_title = (hist.get("title", "") or "").strip()

            if not hist_company or not hist_title:
                continue

            # 公司名匹配（忽略大小写，支持双向包含匹配如 "Apple" vs "Apple Inc."）
            if company != hist_company:
                if company not in hist_company and hist_company not in company:
                    continue

            # 标题相似度
            sim = _title_similarity(title, hist_title)
            if sim > 0.60:
                matched = True
                event_name = _extract_event_keyword(hist_title)
                logger.info("[追踪] 匹配: 「%s」↔ 历史「%s」, sim=%.2f, 事件=%s",
                            title[:30], hist_title[:30], sim, event_name)
                break

        if matched:
            news["is_tracking"] = True
            news["tracking_title"] = f"【追踪·{event_name}】{title}"
            tracking_count += 1
        else:
            news["is_tracking"] = False

    logger.info("[追踪] 标记完成: %d/%d 条为追踪新闻", tracking_count, len(news_list))
    return news_list


def main():
    parser = argparse.ArgumentParser(description="AI科技早报 · 自动生成与发布")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="仅生成本地预览 HTML 文件，不调用微信 API",
    )
    parser.add_argument(
        "--test-wx",
        action="store_true",
        help="使用模拟新闻数据测试微信草稿接口",
    )
    args = parser.parse_args()

    now = datetime.now()
    logger.info("=" * 50)
    logger.info("AI科技早报 · 启动")
    logger.info("当前时间: %s", now.strftime("%Y-%m-%d %H:%M:%S"))

    # ── Step 1: 从多个数据源获取真实新闻 ──
    if args.test_wx:
        logger.info("[main] --test-wx 模式：使用模拟新闻")
        news_list = _mock_news()
    else:
        logger.info("[main] Step 1: 从多个数据源获取真实新闻 ...")
        from news_rss import fetch_all_news, filter_ai_news
        from news_cluster import cluster_events
        from news_agent import rewrite_news

        raw_news = fetch_all_news(hours=24)
        logger.info("[main] 原始数据 %d 条", len(raw_news))

        # 过滤 AI 相关 + 短摘要自动抓取原文
        ai_news = filter_ai_news(raw_news)
        logger.info("[main] AI 相关 %d 条", len(ai_news))

        # 历史去重：剔除已发布过的新闻
        published_ids = _load_published_history()
        ai_news = _filter_published(ai_news, published_ids)

        if not ai_news:
            logger.error("[main] 无 AI 相关新闻，终止")
            sys.exit(1)

        # 事件聚类（同一事件多源合并）
        logger.info("[main] Step 2: 事件聚类合并 ...")
        clustered = cluster_events(ai_news)
        logger.info("[main] 聚类为 %d 个事件", len(clustered))

        # 事件追踪标记：基于近期已发布历史，标记 is_tracking / tracking_title
        recent_history = load_recent_published(days=2)
        clustered_for_rewrite = mark_tracking_news(clustered[:30], recent_history)

        # LLM 多源融合改写（取前 30 个事件，争取更多输出）
        logger.info("[main] Step 3: LLM 多源融合改写 ...")
        news_list = rewrite_news(clustered_for_rewrite)
        logger.info("[main] 改写完成，共 %d 条", len(news_list))

        # 检查来源多样性
        sources = set(n.get("source_name", "") for n in news_list)
        logger.info("[main] 来源分布: %s", sources)
        if len(sources) < 2:
            logger.warning("[main] 来源单一！仅 %s", sources)

        # 数量不足时告警
        if len(news_list) < 10:
            logger.warning("[main] 输出数量偏少（%d 条），建议检查过滤逻辑或输入数量", len(news_list))

    # ── Step 2: 生成 HTML ──
    logger.info("[main] 正在生成微信图文 HTML ...")
    from formatter import build_wechat_html, save_preview_html

    preview_path = save_preview_html(news_list)
    logger.info("[main] 预览文件已保存: %s", preview_path)

    if args.preview:
        logger.info("[main] --preview 模式：跳过微信 API 调用")
        print(f"\n[OK] 预览文件已生成: {preview_path}")
        print("   用浏览器打开即可查看效果。\n")
        return

    # ── Step 3: 检查微信配置 ──
    from config import Config

    if Config.WX_APPID == "your_appid_here" or not Config.WX_APPSECRET:
        logger.error("[main] 微信配置未填写！请先在 .env 中设置 WX_APPID 和 WX_APPSECRET")
        print(f"\n[失败] 微信配置未填写！预览文件已保存至: {preview_path}")
        print("   请先在 .env 文件中设置 WX_APPID 和 WX_APPSECRET，然后重新运行。\n")
        sys.exit(1)

    # ── Step 4: 创建微信草稿 ──
    logger.info("[main] 正在创建微信公众号图文草稿 ...")
    from wechat_api import create_news_draft

    try:
        result = create_news_draft(news_list)
        media_id = result.get("media_id", "未知")
        logger.info("[main] 草稿创建成功！media_id: %s", media_id)

        # 先保存待确认草稿缓存（确保即使后续打印报错也不会丢失）
        _save_pending_draft({
            "media_id": media_id,
            "news_list": news_list,
            "preview_path": preview_path,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        print(f"\n[成功] 草稿创建成功！")
        print(f"   media_id: {media_id}")
        print(f"   预览文件: {preview_path}")
        print(f"   [提示] 尚未保存到已发布历史记录。")
        print(f"   请在微信公众号后台预览确认后，告诉我「已发布」以保存历史去重记录。")
        print(f"   若草稿有问题，我会自动删除预览文件。\n")
    except Exception as e:
        logger.exception("[main] 创建草稿失败")
        print(f"\n[失败] 创建草稿失败: {e}")
        print(f"   预览文件已保存至: {preview_path}，可手动复制内容到微信编辑器。\n")
        sys.exit(1)


def confirm_published(news_list: List[Dict] = None) -> bool:
    """手动保存已发布新闻到历史记录（用户确认已群发后调用）。

    用法：当用户告知已发布后，调用此函数保存历史记录。
    """
    pending = _load_pending_draft()
    nl = news_list or pending.get("news_list", [])
    if not nl:
        logger.warning("[main] 无可保存的已发布新闻（新闻列表为空或缓存已过期）")
        return False
    _save_published_history(nl)
    # 清理预览文件
    preview = pending.get("preview_path", "")
    if preview:
        try:
            Path(preview).unlink(missing_ok=True)
            logger.info("[main] 已删除预览文件: %s", preview)
        except Exception:
            pass
    _clear_pending_draft()
    print(f"\n[已发布] 历史记录已保存！下次运行将跳过这些新闻。")
    return True


def reject_draft() -> bool:
    """拒绝草稿（用户确认草稿有问题不发布后调用）。

    清理预览文件，不保存任何历史记录。
    """
    pending = _load_pending_draft()
    preview = pending.get("preview_path", "")
    if preview:
        try:
            Path(preview).unlink(missing_ok=True)
            logger.info("[main] 已删除预览文件: %s", preview)
        except Exception:
            pass
    _clear_pending_draft()
    print(f"\n[已拒绝] 预览文件已删除，未保存任何历史记录。")
    return True


def _mock_news() -> List[Dict]:
    """模拟新闻数据，用于 --test-wx 模式测试微信接口。"""
    return [
        {
            "title": "OpenAI 发布 GPT-5，推理能力全面升级",
            "summary": "6月9日，OpenAI 在旧金山发布会上正式推出 GPT-5 旗舰模型，在数学推理、代码生成和多模态理解上实现显著突破，综合性能较 GPT-4 提升约 40%。API 价格保持不变，开发者即日起可直接调用，企业级客户可申请私有化部署方案。业内分析认为，这将进一步巩固 OpenAI 在大模型赛道的领先地位，并对 Google、Anthropic 形成直接竞争压力。",
            "company": "OpenAI",
            "source_url": "https://openai.com/blog",
            "source_name": "OpenAI 官方",
            "published_at": "2026-06-09",
        },
        {
            "title": "Google 推出 Gemini 3.0，原生多模态融合",
            "summary": "6月10日凌晨，Google I/O 大会上发布 Gemini 3.0 大模型，首次实现文本、图像、音频、视频的深度原生融合架构，不再依赖独立的视觉或语音模块。性能全面超越上一代，在 MMLU、HumanEval 等基准测试中刷新纪录，推理速度提升 2 倍。目前已集成到 Google Search、Bard 等全线产品中，用户即日起可在美国地区体验。",
            "company": "Google",
            "source_url": "https://blog.google",
            "source_name": "Google Blog",
            "published_at": "2026-06-10",
        },
        {
            "title": "NVIDIA 发布 Blackwell Ultra，AI 算力再翻倍",
            "summary": "6月8日，NVIDIA GTC 大会上正式推出 Blackwell Ultra GPU，采用改进的 4nm 工艺，AI 训练性能较上一代提升 2.5 倍，显存带宽突破 12TB/s，功耗仅增加 15%。同时推出配套的 Grace CPU 超级芯片方案，专门针对万亿参数级大模型训练优化。该产品预计 2026 年下半年开始向数据中心客户交付，AWS、Azure、GCP 已确认首批采购意向。",
            "company": "NVIDIA",
            "source_url": "https://nvidianews.nvidia.com",
            "source_name": "NVIDIA Newsroom",
            "published_at": "2026-06-08",
        },
        {
            "title": "字节跳动豆包大模型月活突破 3 亿",
            "summary": "6月10日，字节跳动宣布旗下豆包 App 月活跃用户突破 3 亿，成为国内用户规模最大的 AI 原生应用之一。豆包最新版本已集成语音通话、图像识别、文档分析等能力，日调用次数超过 10 亿次。字节内部透露，正在基于豆包技术底座开发面向教育、电商、办公等多个垂直行业的 AI 解决方案，预计年内陆续上线。",
            "company": "字节跳动",
            "source_url": "https://www.36kr.com",
            "source_name": "36氪",
            "published_at": "2026-06-10",
        },
        {
            "title": "Meta 开源 Llama 4，百万级上下文创纪录",
            "summary": "6月9日，Meta 正式开源 Llama 4 大模型，支持高达 1M token 的超长上下文窗口，开发者可免费商用。模型采用稀疏 MoE 架构，总参数量达 1.2T，每次推理仅激活约 40B 参数，兼顾性能与效率。发布即提供 PyTorch、JAX、TensorFlow 等多框架支持，社区反响热烈，GitHub 星标 24 小时内突破 5 万。",
            "company": "Meta",
            "source_url": "https://ai.meta.com",
            "source_name": "Meta AI",
            "published_at": "2026-06-09",
        },
        {
            "title": "华为云发布盘古大模型 6.0，深耕行业场景",
            "summary": "6月10日，华为云在开发者大会上推出盘古大模型 6.0，聚焦金融、医疗、制造等行业的深度应用。新版本引入行业知识增强模块，在财务报告分析、医学影像诊断、工业质检等场景准确率提升 15%-25%。同时发布 ModelArts 6.0 平台，支持从数据标注到模型部署的全流程自动化，大幅降低企业 AI 落地门槛，已获 50 余家头部企业签约。",
            "company": "华为",
            "source_url": "https://www.huaweicloud.com",
            "source_name": "华为云",
            "published_at": "2026-06-10",
        },
        {
            "title": "苹果 Apple Intelligence 全面开放中文支持",
            "summary": "6月9日，苹果在 WWDC 大会上宣布 Apple Intelligence 正式支持简体中文、繁体中文和粤语，中国区 iPhone 15 Pro 及以上机型用户可体验 AI 写作助手、图像生成、智能相册整理等功能。苹果强调所有数据处理均在设备端完成，隐私保护仍是核心设计原则。该功能将在 iOS 20 更新中推送，覆盖超过 2 亿中国用户。",
            "company": "Apple",
            "source_url": "https://www.apple.com",
            "source_name": "Apple 官网",
            "published_at": "2026-06-09",
        },
        {
            "title": "Anthropic 发布 Claude 5，安全性刷新纪录",
            "summary": "6月8日，Anthropic 推出 Claude 5 模型，在安全性评估中刷新多项纪录，有害内容拒绝率提升至 99.8%，同时编程和数学能力大幅提升。新模型引入了「可控诚实」训练机制，能在保持高安全标准的前提下减少过度拒绝。API 即日起已开放，企业版支持自定义安全策略配置，多家金融机构已率先接入测试。",
            "company": "Anthropic",
            "source_url": "https://www.anthropic.com",
            "source_name": "Anthropic 官方",
            "published_at": "2026-06-08",
        },
        {
            "title": "微软 Copilot 全面整合 GPT-5，企业用户大增",
            "summary": "6月10日，微软宣布旗下 Copilot 全线产品（M365、GitHub、Azure）已集成 OpenAI GPT-5 模型，响应质量和代码生成准确率显著提升。最新财报显示企业用户同比增长 80%，续费率达 90% 以上。同时推出 Copilot Studio 低代码工具，允许企业基于自有数据定制专属 AI 助手，无需编写复杂代码即可完成部署，已有 3000 家企业参与内测。",
            "company": "Microsoft",
            "source_url": "https://blogs.microsoft.com",
            "source_name": "Microsoft 官方",
            "published_at": "2026-06-10",
        },
        {
            "title": "DeepSeek 发布新一代 MoE 架构模型 V4",
            "summary": "6月9日，DeepSeek 发布 V4 大模型，采用创新的混合专家架构，以不到 Llama 4 十分之一的训练成本实现了接近的性能水平。在中文理解、代码生成、数学推理等任务上表现出色，多项指标超越同规模开源模型。业界认为这是中国 AI 公司在高效训练路线上的重要里程碑，开源社区已开始对该模型进行全面评测。",
            "company": "DeepSeek",
            "source_url": "https://www.deepseek.com",
            "source_name": "DeepSeek 官方",
            "published_at": "2026-06-09",
        },
        {
            "title": "阿里巴巴通义千问推出多模态 3D 生成能力",
            "summary": "6月10日，阿里巴巴通义千问大模型新增 3D 内容生成能力，用户输入文字或图片即可在 30 秒内生成高精度 3D 模型，支持导出 OBJ/FBX/GLTF 等标准格式。该能力已集成到淘宝商品展示和游戏开发场景中，首批合作品牌已实现商品 3D 化展示，点击转化率提升 35%。阿里云同步开放了该能力的 API 接口，开发者可按量付费使用。",
            "company": "阿里巴巴",
            "source_url": "https://tongyi.aliyun.com",
            "source_name": "阿里云",
            "published_at": "2026-06-10",
        },
        {
            "title": "腾讯混元大模型上线视频生成功能",
            "summary": "6月9日，腾讯混元大模型正式开放视频生成能力，用户输入文字描述即可生成长达 60 秒的 1080p 视频，支持风格迁移、角色一致性和镜头运镜控制。该功能通过微信视频号、腾讯视频等场景率先落地，创作者可通过混元助手直接调用。腾讯同步推出了视频素材版权保护方案，采用 AI 水印技术防止侵权滥用。",
            "company": "腾讯",
            "source_url": "https://hunyuandamodel.tencent.com",
            "source_name": "腾讯云",
            "published_at": "2026-06-09",
        },
        {
            "title": "小米 SU7 接入大模型，智能座舱全面升级",
            "summary": "6月10日，小米汽车 SU7 推送最新 OTA 升级，正式接入自研大模型，智能座舱语音助手支持多轮复杂指令、车内设备联动和实时路况推理。用户可用自然语言控制空调、座椅、导航等全部功能，系统还能根据驾驶习惯主动推荐场景模式。小米称该更新将使座舱交互体验从「指令式」跃升至「对话式」，首批已推送至超过 10 万辆车。",
            "company": "小米",
            "source_url": "https://www.xiaomi.com",
            "source_name": "小米官方",
            "published_at": "2026-06-10",
        },
        {
            "title": "特斯拉 Optimus 机器人实现工厂全自动装配",
            "summary": "6月8日，特斯拉 Optimus 人形机器人在弗里蒙特工厂实现全自动装配线初步部署，可完成零件搬运、螺丝拧紧、线束连接等 20 余种工序，失误率低于人工操作。马斯克在社交媒体上表示，Optimus 将在 2027 年实现量产，目标售价降至 2 万美元以下，未来将作为通用工业机器人向全球工厂推广，目前已接到多家制造企业的预订意向。",
            "company": "Tesla",
            "source_url": "https://www.tesla.com",
            "source_name": "Tesla 官方",
            "published_at": "2026-06-08",
        },
    ]


if __name__ == "__main__":
    main()
