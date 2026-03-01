# -*- coding: utf-8 -*-
"""
Markdown 格式化 — 信息充分、重点突出、紧凑可读。

结构：AI 精炼分析在前（重点），原始数据表在后（充分信息）。
"""

from __future__ import annotations

from newsbot.config import DATA_SOURCES_LINE, log


def _compact_table(items: list[dict], show_score: bool = True) -> str:
    """紧凑表格：序号 + 标题 + 可选热度，不画表格线。"""
    if not items:
        return "_暂无数据_\n"
    lines: list[str] = []
    for item in items:
        score = f"  `{item['hot_score']}`" if show_score and item.get("hot_score") else ""
        lines.append(f"{item['rank']}. {item['title']}{score}")
    return "\n".join(lines) + "\n"


def format_full_report(
    date_str: str,
    ai_results: dict[str, str],
    cn_trending: dict[str, list[dict]],
    hk_tw_data: dict[str, list[dict]],
    xiaohongshu: list[dict],
    reddit_data: dict[str, dict[str, list[dict]]],
    rss_data: dict[str, dict[str, list[dict]]],
    global_news: list[dict] | None = None,
    hackernews: list[dict] | None = None,
) -> str:
    s: list[str] = []

    # ── 头部
    s.append(f"# ☀️ 早知天下事 · {date_str}\n")
    s.append(f"> {DATA_SOURCES_LINE}\n")

    # ══════ 华人圈 ══════
    s.append("---")
    s.append("## 🇨🇳 华人圈要点\n")
    cn = ai_results.get("cn", "")
    if cn:
        s.append(cn)
    else:
        s.append("_AI 分析未生成_")
    s.append("")

    # ── 各平台热搜（全量保留）
    s.append("---")
    s.append("## 📊 各平台热搜\n")

    cn_platforms = [
        ("🔴 微博", "微博热搜"),
        ("🔵 百度", "百度热搜"),
        ("🟡 知乎", "知乎热榜"),
        ("🎬 B站", "哔哩哔哩"),
        ("🎵 抖音", "抖音热搜"),
        ("📰 头条", "今日头条"),
        ("💬 微信", "微信热文"),
        ("📋 澎湃", "澎湃热榜"),
    ]
    for label, key in cn_platforms:
        items = cn_trending.get(key, [])
        if items:
            s.append(f"**{label}**")
            s.append(_compact_table(items))

    # 港台
    hktw_platforms = [
        ("🇹🇼 PTT", "PTT（台湾）"),
        ("🇹🇼 Google News台湾", "Google News台湾"),
        ("🇭🇰 LIHKG", "LIHKG（香港）"),
        ("🇭🇰 Google News香港", "Google News香港"),
    ]
    for label, key in hktw_platforms:
        items = hk_tw_data.get(key, [])
        if items:
            s.append(f"**{label}**")
            s.append(_compact_table(items, show_score=key.startswith("Google") is False))

    # Reddit 华人
    reddit_cn = reddit_data.get("cn", {})
    if reddit_cn:
        s.append("**🌐 Reddit 华人社区**")
        all_items: list[dict] = []
        for sub_items in reddit_cn.values():
            all_items.extend(sub_items)
        for i, item in enumerate(all_items[:10], 1):
            item["rank"] = i
        s.append(_compact_table(all_items[:10]))

    # ══════ 国际 ══════
    s.append("---")
    s.append("## 🌍 国际要点\n")
    intl = ai_results.get("intl", "")
    if intl:
        s.append(intl)
    else:
        s.append("_AI 分析未生成_")
    s.append("")

    # ── 国际 RSS 原始数据（全量保留，但标注来源国）
    s.append("---")
    s.append("## 📡 国际新闻源\n")

    region_labels = {
        "vn": "🇻🇳 越南", "jp": "🇯🇵 日本", "kr": "🇰🇷 韩国",
        "in": "🇮🇳 印度", "id": "🇮🇩 印尼",
        "us": "🇺🇸 美国", "uk": "🇬🇧 英国", "de": "🇩🇪 德国", "fr": "🇫🇷 法国",
    }
    for region_key in ("vn", "jp", "kr", "in", "id", "us", "uk", "de", "fr"):
        feeds = rss_data.get(region_key, {})
        if not feeds:
            continue
        label = region_labels.get(region_key, region_key)
        s.append(f"**{label}**")
        for source_name, items in feeds.items():
            if items:
                s.append(f"*{source_name}*")
                s.append(_compact_table(items, show_score=False))

    # Reddit 国际
    for rk, rk_label in [("asia", "🌏 Reddit 亚太"), ("west", "🌍 Reddit 欧美")]:
        rd = reddit_data.get(rk, {})
        if rd:
            s.append(f"**{rk_label}**")
            for sub, items in rd.items():
                if items:
                    s.append(f"*{sub}*")
                    s.append(_compact_table(items))

    # 全球 + Hacker News
    if global_news:
        s.append("**🌐 Google News 全球**")
        s.append(_compact_table(global_news, show_score=False))

    if hackernews:
        s.append("**💻 Hacker News**")
        s.append(_compact_table(hackernews, show_score=False))

    # ── 尾部
    s.append("---")
    s.append(f"*📡 数据采集自 20+ 平台 · AI 分析由 DeepSeek 生成*")

    return "\n".join(s)
