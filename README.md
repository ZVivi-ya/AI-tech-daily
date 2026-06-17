# AI科技早报

每天自动抓取全球AI科技资讯，经AI筛选、聚类、改写后生成微信公众号图文草稿。

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

每条新闻以 `【公司/主题】` 格式标题开头，摘要为150-250字精炼中文。
预览文件保存在 `output/` 目录下，用浏览器打开即可查看。

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
├── .env.example         # 环境变量模板
├── requirements.txt     # Python依赖
└── .gitignore
```
