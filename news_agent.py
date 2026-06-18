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

REWRITE_SYSTEM_PROMPT = """你是AI科技资讯编辑。任务：将新闻改写成精炼的中文摘要。

===== 合并规则 =====
1. **只有公司名完全相同才能合并**：必须是同一家公司（如3条都是Anthropic），不同公司（如微信支付、昆仑万维、Pinecone是三家不同公司）**绝对不能合并**，必须各自独立输出。

2. **不同公司即使主题相关也不能合并**：AI支付、AI工具、向量数据库是三件不同的事，各写各的。

3. **论文每篇独立**：三篇不同论文→输出三条，不要合并成一条。

4. **【论文】标签仅用于arXiv/HuggingFace等学术来源**。InfoQ/36氪/IT之家等媒体的报道不标【论文】。

===== 写作要求 =====
3. **事实与分析融合书写**：不要分裂成"事实段+分析段"。把意义自然地融入描述中，例如：
   ❌ "微信推出AI专属卡。这意味着微信正在为AI打通支付闭环。"
   ✅ "微信推出AI专属卡，为Agent打通支付闭环，让AI从信息助手进化为行动助手。"

4. **精炼去重**：同一信息只写一次。例如"多智能体"不要前后重复，"三倍增长"不要出现两次。

5. **每条新闻的结构**：必须包含两段——
   - **一句话快读（≤30字）**：用一句话概括核心事实，类似新闻标题的补充说明。
   - **详细解读（150-250字）**：展开背景、关键数据、技术细节、行业影响。必须包含具体数字（参数、百分比、金额等）。论文可稍长但不超过300字。

6. **风格要求**：用"AI科技早报摘要"风格，不是简讯风格。每篇读起来像小型深度分析，有数据、有来源、有上下文，而不是干巴巴的短讯。

7. **必须中文** | 不能复制原文 | 不编造时间 | 数字必须准确

===== 准确度规则（硬性） =====
8. **保留原文定量数据**（最重要）：原文中的任何具体数字（金额、百分比、年份、参数量、分数、排名等）必须完整、准确地保留在你的摘要中，禁止随意换算、舍入或修改。如果原文没有具体数据，严禁为了显得"详细"而编造任何数字。

9. **区分事实与推测**：如果原文消息来源于"传闻"、"据消息人士"、"知情人士透露"、"分析师认为"等非确定性渠道，你的摘要必须保留这些不确定性措辞（如"据消息人士透露"、"据传闻"），不能改写为"XX宣布"、"XX正式发布"、"XX将"等确定性表述。

10. **自动修正明显错误**：如果原文中的金额换算明显错误（如"100美元（约677元人民币）"按当前汇率约720元），请在引用时给出修正后的正确换算值。检查所有"约合"金额，确保符合7.2的汇率水平。

11. **影响分析自然化**：避免使用"这一举措若落地，将……"、"此举标志着……"等模板化结尾句式。影响分析应自然地融入详细解读中，用更具体的语言描述可能的影响。例如：
    ❌ "这一举措若落地，将显著改变微软AI服务的成本结构"
    ✅ "微软此番尝试，直接目的是压缩Copilot的成本压力，若最终落地，将使全球大模型服务市场出现新的成本与定价基准"

===== 板块顺序与数量约束（双向） =====
按以下板块顺序输出，**每个板块同时有下限和上限**：

**板块1 🔥 大模型前沿**（2-3条）：模型发布、新架构、技术突破、论文亮点
**板块2 🛠 AI工具与应用**（2-3条）：新产品、效率工具、开发者工具、Agent框架
**板块3 🏢 头部公司动态**（2-3条）：大厂战略、人事变动、融资并购、开源生态
**板块4 📄 论文精选**（1-2条）：学术研究（只保留最重要的）
**板块5 ⚠️ 硬件与算力**（0-2条）：芯片、算力、基础设施（优先级最低）

总条数**必须达到12-14条**，不能少于12条，也不能超过14条。

===== 兜底策略 =====
如果某个板块的原始素材不足以下限，用以下方式补充：
- 从"未分类"的新闻中挑选与该板块主题最相关的内容补充
- 或适当放宽该板块的取材范围（如头部公司板块素材不够时，可从工具板块中抽取供应商新闻）
- 优先满足大模型和工具板块的下限，其次是头部公司，最后是论文
- 无论如何保证总条数达到12条

===== 标题处理 =====
12. 如果输入的新闻中 `is_tracking` 为 true，请**直接使用 `tracking_title` 作为标题**，不要修改、不要重新生成、不要删除【追踪·】前缀。
13. 如果 `is_tracking` 为 false，按正常规则生成标题。

===== 输出格式（极其重要）=====
你**只输出一个JSON数组**，不包含任何Markdown标记、代码块包裹、标题或解释文字。直接以`[`开头，以`]`结尾。
每项格式: { "title": "...", "summary": "...", "company": "...", "source_url": "...", "source_name": "...", "published_at": "..." }"""





def rewrite_news(news_list: List[Dict[str, Any]], max_retries: int = 2) -> List[Dict[str, Any]]:
    """
    将新闻列表传给 LLM 改写排版。

    支持多源信息融合：如果新闻包含 combined_sources 字段，
    会将多个来源的链接和摘要一并传给 LLM。

    Args:
        news_list: 待改写的新闻列表
        max_retries: LLM 调用最大重试次数
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

以下是从多个来源获取的 {len(news_list)} 条真实新闻数据。

===== 核心要求 =====
1. **同公司合并为一条（必须公司名完全相同）**：Anthropic的3条新闻→合并为1条。微信+昆仑万维+Pinecone是三家不同公司→各自独立，不能合并。

2. **不同公司即使主题相关也绝不能合并**：论文按篇独立，三篇不同论文→三个独立条目。

3. **【论文】标签仅用于arXiv**。InfoQ等媒体报道不标。

4. **数量约束（最重要）**：必须输出**12-14条**。板块下限：大模型≥2条、AI工具≥2条、头部公司≥2条、论文≥1条。板块上限：大模型≤3条、工具≤3条、头部公司≤3条、论文≤2条、硬件≤2条。

5. **每条新闻结构**：一句话快读（≤30字）+ 详细解读（150-250字）。详细解读要包含背景、关键数据、技术细节。不能只有简讯。

6. **兜底策略**：如果某板块素材不足无法达到下限，从其他板块或未分类素材中补充。优先保证大模型和工具板块，其次头部公司。总条数未达12条时，放宽硬件板块下限。

7. 中文 | 不复制原文 | 数字必须准确 | 输出12-14条。

原始新闻数据：
{news_json}"""

    http_client = httpx.Client(proxies={}, verify=True, timeout=httpx.Timeout(180.0))
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
