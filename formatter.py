"""
微信图文 HTML 生成器 —— 生成类似"8点1氪"风格的早报图文内容
"""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List

from config import Config

logger = logging.getLogger(__name__)

# 中国时区偏移
import time as _time
CST_OFFSET = _time.timezone if _time.localtime().tm_isdst else _time.timezone
CST_OFFSET = 8 * 3600  # UTC+8

# ─── 模板片段 ───

HTML_HEADER = """\
<section style="padding: 10px 0;">
  <section style="background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08);">
"""

HTML_FOOTER = """\
  </section>
</section>
"""

# Banner 头部
def _build_banner(date_str: str, weekday_cn: str) -> str:
    return f"""\
    <section style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 32px 24px; text-align: center;">
      <p style="font-size: 28px; font-weight: bold; color: #ffffff; margin: 0 0 8px 0; letter-spacing: 2px;">AI 科技早报</p>
      <p style="font-size: 14px; color: rgba(255,255,255,0.85); margin: 0;">{date_str} · {weekday_cn}</p>
      <p style="font-size: 12px; color: rgba(255,255,255,0.6); margin: 6px 0 0 0;">每天8点，带你速览全球AI大事件</p>
    </section>"""


# 单条新闻卡片
def _build_news_card(i: int, item: dict) -> str:
    title = _escape_html(item.get("title", ""))
    raw_summary = item.get("summary", "")
    company = _escape_html(item.get("company", ""))
    source_url = _escape_html(item.get("source_url", ""))
    source_name = _escape_html(item.get("source_name", ""))
    published_at = _escape_html(item.get("published_at", ""))

    # 公司标签
    company_badge = ""
    if company:
        company_badge = f'<span style="display: inline-block; background: #eef2ff; color: #667eea; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-bottom: 6px;">{company}</span>'

    # 时间标签
    time_badge = ""
    if published_at:
        time_badge = f'<span style="display: inline-block; background: #fef3c7; color: #b45309; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-bottom: 6px; margin-left: 4px;">{published_at}</span>'

    # 来源 + 原文链接（显示为文字，不可点击，仅供查阅）
    ref_html = ""
    if source_url and source_name:
        url_display = source_url.replace("https://", "").replace("http://", "").rstrip("/")
        ref_html = (
            f'<p style="font-size: 11px; color: #aaa; margin: 4px 0 0 0; line-height: 1.4;">'
            f'来源：{source_name} ｜ 详情请查看原文：{url_display}</p>'
        )

    # summary：按空行拆分为多个段落，清理标记符号
    summary_paragraphs = _build_summary_paragraphs(raw_summary)

    return f"""\
    <section style="padding: 16px 20px; border-bottom: 1px solid #f0f0f0;">
      <section style="display: flex; align-items: flex-start; gap: 12px;">
        <span style="display: inline-flex; align-items: center; justify-content: center; min-width: 28px; height: 28px; background: #667eea; color: #fff; font-size: 14px; font-weight: bold; border-radius: 50%; flex-shrink: 0;">{i}</span>
        <section style="flex: 1; min-width: 0;">
          <p style="font-size: 15px; font-weight: bold; color: #333; margin: 0 0 6px 0; line-height: 1.5;">{title}</p>
          <p style="margin: 0 0 6px 0;">{company_badge}{time_badge}</p>
          {summary_paragraphs}
          {ref_html}
        </section>
      </section>
    </section>"""


# 尾部运营语 + 免责声明
OPERATION_FOOTER = """\
    <section style="padding: 20px 24px; text-align: center; background: #fafafa;">
      <p style="font-size: 12px; color: #999; margin: 0 0 8px 0; line-height: 1.8;">
        以上内容综合自 36氪、少数派、InfoQ 等媒体公开报道<br>
        由 AI 自动整理为资讯摘要，仅供参考，不构成任何建议<br>
        具体信息请查看各原文章节，版权归原作者所有
      </p>
      <p style="font-size: 12px; color: #bbb; margin: 0;">
        — — — — — — — — — — —<br>
        关注我，每天8点收获 AI 前沿资讯
      </p>
    </section>"""


def build_wechat_html(news_list: List[Dict[str, Any]]) -> str:
    """
    根据新闻列表生成微信图文 HTML。

    参数：
        news_list: 字典列表，每项含 title, summary, company, source_url, source_name

    返回：
        可直接作为微信图文正文的 HTML 字符串
    """
    now = datetime.now()
    weekday_map = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    date_str = "{0}年{1}月{2}日".format(now.year, now.month, now.day)
    weekday_cn = weekday_map[now.weekday()]

    parts = [HTML_HEADER]
    parts.append(_build_banner(date_str, weekday_cn))

    # 新闻计数标题
    parts.append(f"""\
    <section style="padding: 14px 20px; background: #f8f9ff;">
      <p style="font-size: 13px; color: #667eea; font-weight: bold; margin: 0;">今日快讯 · 共 {len(news_list)} 条</p>
    </section>""")

    for idx, item in enumerate(news_list, start=1):
        parts.append(_build_news_card(idx, item))

    parts.append(OPERATION_FOOTER)
    parts.append(HTML_FOOTER)

    html = "\n".join(parts)
    logger.info("[formatter] 生成 HTML，长度 %d 字符", len(html))
    return html


def save_preview_html(news_list: List[Dict[str, Any]]) -> str:
    """
    生成本地预览 HTML 文件并返回路径。
    预览版添加 Meta viewport，方便在手机浏览器中查看效果。
    """
    now = datetime.now()
    weekday_map = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    date_str = "{0}年{1}月{2}日".format(now.year, now.month, now.day)
    weekday_cn = weekday_map[now.weekday()]

    body_html = build_wechat_html(news_list)

    full_html = f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>AI科技早报 · {date_str}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #f5f5f5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; padding: 16px; }}
</style>
</head>
<body>
{body_html}
<p style="text-align:center; color:#bbb; font-size:12px; margin-top:16px;">预览模式 · 实际群发效果以微信客户端为准</p>
</body>
</html>"""

    filename = f"preview_{now.strftime('%Y%m%d_%H%M')}.html"
    out_path = Config.HTML_OUTPUT_DIR / filename
    out_path.write_text(full_html, encoding="utf-8-sig")  # utf-8-sig 加 BOM，避免 Windows 下浏览器用 GBK 解析导致乱码
    logger.info("[formatter] 预览文件已保存: %s", out_path)
    return str(out_path)


def _build_summary_paragraphs(raw: str) -> str:
    """将摘要按段落拆分，清理标记符号，每个段落独立<p>。"""
    if not raw:
        return ""
    # 按空行拆分段落
    paragraphs = re.split(r'\n\s*\n', raw.strip())
    html_parts = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # 清理：去掉 ** 标记（保留文字）
        para = re.sub(r'\*\*(.*?)\*\*', r'\1', para)
        # 清理：去掉 ❓ 符号
        para = para.replace('❓', '')
        # 转义HTML
        para = _escape_html(para)
        # 每个段落一个 <p>
        html_parts.append(
            f'<p style="font-size: 13px; color: #444; margin: 0 0 6px 0; line-height: 1.7;">{para}</p>'
        )
    if not html_parts:
        return ""
    return '\n          '.join(html_parts)


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )
