# -*- coding: utf-8 -*-
"""
数据导出模块 — 生成可供外部 AI 分析的结构化文件。

产出两份文件：
  1. posts_raw_{type}_{date}.json   — 完整 JSON 原始数据
  2. analysis_ready_{type}_{date}.md — 结构化 Markdown，可直接粘贴到任意 AI 客户端
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sentiment.config.settings import BEIJING, EXPORT_DIR, log
from sentiment.core.stats import stats_text


def _safe_name(s: str, max_len: int = 40) -> str:
    """移除文件名不安全字符，截断长度。"""
    import re
    s = re.sub(r'[\\/:*?"<>|\s]+', '_', s)
    s = s.strip('_')
    return s[:max_len] if len(s) > max_len else s


def make_tag(profile: dict) -> str:
    """从 profile 生成描述性标签，用于文件名和路径。"""
    keywords = profile.get("keywords", [])
    kw_part = "_".join(keywords[:3])

    from sentiment.config.settings import ALL_PLATFORMS
    plat_keys = profile.get("_platforms", [])
    if plat_keys and len(plat_keys) <= 4:
        plat_names = [ALL_PLATFORMS.get(p, p) for p in plat_keys]
        plat_part = "_".join(plat_names)
    elif plat_keys:
        plat_part = f"{len(plat_keys)}平台"
    else:
        plat_part = ""

    parts = [p for p in [kw_part, plat_part] if p]
    tag = "_".join(parts) if parts else profile.get("id", "unknown")
    return _safe_name(tag)


def _make_filename(profile: dict, ext: str, prefix: str = "") -> Path:
    ts = datetime.now(BEIJING).strftime("%Y%m%d_%H%M")
    tag = make_tag(profile)
    name = f"{prefix}{tag}_{ts}.{ext}"
    return EXPORT_DIR / name


def export_raw_json(posts: list[dict], profile: dict) -> Path:
    """导出完整 JSON 原始数据。"""
    path = _make_filename(profile, "json", prefix="posts_raw_")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    log.info("已导出原始 JSON: %s (%d 条)", path.name, len(posts))
    return path


def export_analysis_markdown(posts: list[dict], stats: dict, profile: dict) -> Path:
    """
    导出结构化 Markdown 分析材料。
    可直接粘贴到 ChatGPT / Claude / Gemini 等 AI 客户端做深度分析。
    """
    from sentiment.core.collector import range_for_days

    start_dt, end_dt = range_for_days(profile["days"])
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = end_dt.strftime("%Y-%m-%d")

    total = stats["total"]
    sentiment = stats["sentiment"]
    plat_items = stats["platform"].most_common()

    sections = []

    # ── 头部概况
    sections.append(f"# {profile['title']} — 采集数据与统计\n")
    sections.append(f"**采集时间**: {start_s} ~ {end_s} ({profile['days']}天)")
    sections.append(f"**关键词**: {', '.join(profile['keywords'])}")
    sections.append(f"**帖子总量**: {total} 条")
    sections.append(f"**覆盖平台**: {', '.join(f'{p}({c}条)' for p, c in plat_items)}")
    sections.append("")

    # ── 情绪分布
    sections.append("## 情绪分布\n")
    for label in ("正面", "中性", "负面"):
        cnt = sentiment[label]
        pct = cnt / max(total, 1) * 100
        sections.append(f"- {label}: {cnt} 条 ({pct:.1f}%)")
    sections.append("")

    # ── 高频词 Top 30
    sections.append("## 高频词 Top 30\n")
    sections.append("| 排名 | 关键词 | 出现次数 |")
    sections.append("|------|--------|----------|")
    for i, (word, cnt) in enumerate(stats["top_words"], 1):
        sections.append(f"| {i} | {word} | {cnt} |")
    sections.append("")

    # ── 完整统计参考
    sections.append("## 统计参考（完整）\n")
    sections.append("```")
    sections.append(stats_text(stats))
    sections.append("```\n")

    # ── 全量帖子
    sections.append("## 全量帖子数据\n")
    sections.append(f"共 {total} 条，按平台分组：\n")

    posts_by_plat: dict[str, list[dict]] = {}
    for p in posts:
        posts_by_plat.setdefault(p["platform"], []).append(p)

    for plat, plat_posts in sorted(posts_by_plat.items(), key=lambda x: -len(x[1])):
        sections.append(f"### {plat} ({len(plat_posts)} 条)\n")
        for idx, p in enumerate(plat_posts, 1):
            title_part = f"**{p['title']}** — " if p.get("title") else ""
            content = p["content"][:300]
            url_part = f" [{p['url'][:60]}]" if p.get("url") else ""
            sections.append(f"{idx}. {title_part}{content}{url_part}")
        sections.append("")

    # ── 尾部 prompt 模板
    sections.append("---\n")
    sections.append("## 建议 Prompt（可直接粘贴到 AI 客户端）\n")
    subject = profile.get("subject", "品牌")
    sections.append(f"""```
你是一名资深游戏舆情与社区生态分析师。以下是{subject}在中国大陆社交媒体上 {start_s} 至 {end_s} 期间的采集数据和统计。

请基于这些数据，结合你的联网搜索能力，输出一份结构完整的舆情分析报告，包含：
1. 执行摘要（带数据的要点概括）
2. 舆情主题 Top 7（触发原因、平台分布、情绪倾向、代表性原文、风险级别）
3. 平台分层对比
4. 玩家情绪结构与诉求
5. 典型玩家画像
6. 风险与机会清单
7. 附录关键词

原则：不编造数据，所有结论需有样本或统计支撑。
```""")
    sections.append("")

    path = _make_filename(profile, "md", prefix="analysis_ready_")
    content = "\n".join(sections)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("已导出分析材料: %s (%d 字)", path.name, len(content))
    return path


def export_all(posts: list[dict], stats: dict, profile: dict) -> dict[str, Path]:
    """导出全部文件，返回 {类型: 路径} 映射。"""
    return {
        "raw_json": export_raw_json(posts, profile),
        "analysis_md": export_analysis_markdown(posts, stats, profile),
    }
