"""
将最新预览HTML发布到公众号草稿箱
"""
import re
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from wechat_api import create_draft


def extract_body_content(html: str) -> str:
    """
    从完整HTML文档中提取<body>内的内容（不含<body>标签本身），
    并移除预览模式提示段落。
    """
    # 提取 <body> 和 </body> 之间的内容
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
    if not body_match:
        raise ValueError("未找到 <body> 标签")
    
    content = body_match.group(1).strip()
    
    # 移除预览模式提示段落
    content = re.sub(
        r'<p\s+style="text-align:center;[^"]*color:#bbb[^"]*">预览模式[^<]*</p>',
        '',
        content,
        flags=re.IGNORECASE
    )
    
    # 清理可能残留的空白
    content = re.sub(r'\n\s*\n+', '\n', content)
    
    return content.strip()


def get_latest_preview() -> Path:
    """获取 output 目录下最新的 preview_*.html 文件。"""
    output_dir = Path(__file__).parent / "output"
    preview_files = sorted(
        output_dir.glob("preview_*.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if not preview_files:
        raise FileNotFoundError("未找到 preview_*.html 文件")
    return preview_files[0]


def main():
    preview_path = get_latest_preview()
    print(f"[publish] 读取预览文件: {preview_path.name}")

    html = preview_path.read_text(encoding="utf-8")
    body_content = extract_body_content(html)

    # 从预览文件标题中提取日期
    title_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', html)
    if title_match:
        year, month, day = title_match.groups()
        draft_title = f"AI科技早报 · {year}年{month}月{day}日"
    else:
        from datetime import datetime
        now = datetime.now()
        draft_title = f"AI科技早报 · {now.year}年{now.month}月{now.day}日"

    print(f"[publish] 草稿标题: {draft_title}")
    print(f"[publish] 正文长度: {len(body_content)} 字符")

    result = create_draft(draft_title, body_content)

    media_id = result.get("media_id", "")
    print("\n[成功] 草稿创建成功！")
    print("   media_id: {}".format(media_id))
    print("   请前往公众号后台「素材管理 → 草稿箱」查看并发布。")


if __name__ == "__main__":
    main()
