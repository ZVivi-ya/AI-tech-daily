# AI科技早报

每天自动抓取全球AI科技资讯，经AI筛选、聚类、改写后生成微信公众号图文草稿。

## 版本

**v2.0-stable** | 2026-06-18

| 核心能力 | 说明 |
|----------|------|
| 14条两段式摘要 | 每条新闻含「一句话快读(≤30字)+详细解读(150-250字)」双层结构 |
| 来源权威评分 | 聚类合并时按来源权威度（量子位92~TLDR AI 52）选择主来源 |
| 事件追踪逻辑 | 基于已发布历史，对持续发酵事件自动添加【追踪·】前缀 |
| 多策略原文抓取 | readability / BS选择器 / 快讯规则 / 纯文本 逐级兜底，MAX_FULLTEXT_CHARS=3000 |
| 微信公众号发布 | access_token缓存，IP白名单管理，一键发布草稿 |

## 功能流程

```
RSS/搜索抓取 → AI关键词过滤 → 事件聚类 → DeepSeek改写 → 微信草稿发布
```

## 支持的新闻源

- **中文科技媒体**：36氪、少数派、InfoQ、IT之家、爱范儿、钛媒体、量子位
- **英文科技媒体**：TechCrunch、CNET、The Verge、WIRED
- **AI前沿**：arXiv AI论文、Hugging Face Blog
- **社区/聚合**：Hacker News、TLDR AI

## 快速开始

1. 复制配置模板：
   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env`，填入你的 API Key：
   - `DEEPS_API_KEY`：DeepSeek API Key（[获取](https://platform.deepseek.com/api_keys)）
   - `WX_APPID` / `WX_APPSECRET`：微信公众号 AppID 和 AppSecret
   - `THUMB_MEDIA_ID`：（可选）封面图媒体ID

3. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

4. 运行：
   ```bash
   python main.py              # 完整流程：抓取 → 改写 → 创建微信草稿
   python main.py --preview    # 仅生成本地预览 HTML
   ```

## 输出格式

每条新闻以**新闻标题**开头，包含公司标签、发布时间和两段式结构：
- **一句话快读（≤30字）**：核心事实一句话概括
- **详细解读（150-250字）**：背景、关键数据、技术细节、行业影响

追踪中的新闻标题自动添加 `【追踪·事件名】` 前缀。
预览文件保存在 `output/` 目录下，用浏览器打开即可查看。

## 快速发布

```bash
python main.py              # 完整流程：抓取 → 改写 → 创建微信草稿
python main.py --preview    # 仅生成本地预览 HTML
python publish_preview.py   # 将最新 preview_*.html 一键发布到公众号草稿箱
```

## 项目结构

```
├── main.py              # 主入口
├── config.py            # 配置读取
├── news_rss.py          # RSS抓取 + AI关键词过滤
├── news_fetcher.py      # 原文内容抓取
├── news_cluster.py      # 事件聚类合并
├── news_agent.py        # DeepSeek LLM 改写
├── formatter.py         # 微信图文 HTML 生成
├── wechat_api.py        # 微信公众号 API
├── publish_preview.py   # 一键发布预览到草稿箱
├── .env.example         # 环境变量模板
├── requirements.txt     # Python依赖
├── .gitignore
└── output/              # 预览 HTML 输出目录
```
