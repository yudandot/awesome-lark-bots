# -*- coding: utf-8 -*-
"""
AI 分析引擎 — 精炼有力、重点突出的每日简报。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from core.llm import chat_completion
from newsbot.config import log


def _fmt_trending(data: dict[str, list[dict]]) -> str:
    lines: list[str] = []
    for platform, items in data.items():
        if not items:
            continue
        lines.append(f"\n【{platform}】")
        for item in items[:10]:
            score = f" ({item['hot_score']})" if item.get("hot_score") else ""
            lines.append(f"  {item['rank']}. {item['title']}{score}")
    return "\n".join(lines)


def _fmt_rss(data: dict[str, list[dict]]) -> str:
    lines: list[str] = []
    for source, items in data.items():
        if not items:
            continue
        lines.append(f"\n【{source}】")
        for item in items[:8]:
            lines.append(f"  {item['rank']}. {item['title']}")
    return "\n".join(lines)


def _fmt_reddit(data: dict[str, list[dict]]) -> str:
    lines: list[str] = []
    for sub, items in data.items():
        if not items:
            continue
        lines.append(f"\n【{sub}】")
        for item in items[:6]:
            lines.append(f"  {item['rank']}. {item['title']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 华人圈
# ---------------------------------------------------------------------------

CN_SYSTEM = """你是一位信息简报编辑。基于多平台热搜数据，写一段华人圈今日要点分析。

要求：
1. 列出 **6-8 条今日最重要的事**，按重要性排序
2. 每条格式：**加粗事件名** — 一句话核心事实 + 一句话为什么重要（标注出现平台）
3. 最后一段 **「今日一句」**：用一句话概括今天华人圈的核心主题

风格：简洁有力，不用学术语言，像给老板写的晨报摘要。
控制总长度在 400-600 字。用中文。"""


def analyze_cn(
    cn_trending: dict[str, list[dict]],
    hk_tw_data: dict[str, list[dict]],
    reddit_cn: dict[str, list[dict]],
    global_news: list[dict],
    date_str: str,
) -> str:
    trending = _fmt_trending(cn_trending)
    hktw = _fmt_trending(hk_tw_data)
    reddit = _fmt_reddit(reddit_cn)
    gnews = ""
    if global_news:
        gnews = "\n【Google News 全球】\n"
        for item in global_news[:10]:
            gnews += f"  {item.get('rank','')}. {item['title']}\n"

    user = f"""{date_str} 各平台热榜：

=== 中国大陆 ===
{trending}

=== 港台 ===
{hktw}

=== 海外华人 ===
{reddit}
{gnews}"""

    try:
        r = chat_completion(provider="deepseek", system=CN_SYSTEM,
                            user=user, temperature=0.4)
        log.info("华人圈分析: %d 字", len(r))
        return r
    except Exception as e:
        log.error("华人圈分析失败: %s", e)
        return ""


# ---------------------------------------------------------------------------
# 国际（全部翻译为中文，精炼输出）
# ---------------------------------------------------------------------------

INTL_SYSTEM = """你是一位国际新闻简报编辑。你会收到多国媒体的原始新闻标题（包含越南语、日语、韩语、印尼语、德语、法语、英语等），以及 Reddit 和 Hacker News 的内容。

任务：翻译、筛选、整合成一份中文国际简报。

要求：
1. **全部翻译为中文**，不保留任何外语原文
2. 分三个板块输出：

**🌏 国际大事**（5-6条）
每条：**加粗事件名** — 一句话说清楚 + 与中国/亚洲的关联（标注来源国）

**🔬 科技前沿**（2-3条）
每条：**加粗主题** — 一句话要点（来自 Hacker News / Reddit 等）

**📝 今日一句**：20字概括全球今日核心

风格：简洁、信息密度高、不啰嗦。控制总长度在 400-500 字。全部中文。"""


def analyze_intl(
    rss_data: dict[str, dict[str, list[dict]]],
    reddit_data: dict[str, dict[str, list[dict]]],
    global_news: list[dict],
    hackernews: list[dict],
    date_str: str,
) -> str:
    parts: list[str] = []
    names = {
        "vn": "越南", "jp": "日本", "kr": "韩国",
        "in": "印度", "id": "印尼",
        "us": "美国", "uk": "英国", "de": "德国", "fr": "法国",
    }
    for key in ("vn", "jp", "kr", "in", "id", "us", "uk", "de", "fr"):
        feeds = rss_data.get(key, {})
        if feeds:
            parts.append(f"\n=== {names.get(key, key)} ===")
            parts.append(_fmt_rss(feeds))

    for rk in ("asia", "west"):
        rd = reddit_data.get(rk, {})
        if rd:
            parts.append(f"\n=== Reddit {rk} ===")
            parts.append(_fmt_reddit(rd))

    if global_news:
        parts.append("\n=== Google News ===")
        for item in global_news[:10]:
            parts.append(f"  {item.get('rank','')}. {item['title']}")

    if hackernews:
        parts.append("\n=== Hacker News ===")
        for item in hackernews[:10]:
            parts.append(f"  {item.get('rank','')}. {item['title']}")

    if not any(p.strip() for p in parts):
        return ""

    user = f"""{date_str} 国际各平台新闻（包含多种外语，请全部翻译为中文）：
{"".join(parts)}"""

    try:
        r = chat_completion(provider="deepseek", system=INTL_SYSTEM,
                            user=user, temperature=0.4)
        log.info("国际分析: %d 字", len(r))
        return r
    except Exception as e:
        log.error("国际分析失败: %s", e)
        return ""


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def run_all_analysis(
    cn_trending: dict[str, list[dict]],
    hk_tw_data: dict[str, list[dict]],
    reddit_data: dict[str, dict[str, list[dict]]],
    global_news: list[dict],
    rss_data: dict[str, dict[str, list[dict]]],
    date_str: str,
    hackernews: list[dict] | None = None,
) -> dict[str, str]:
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {}
        futs[pool.submit(
            analyze_cn, cn_trending, hk_tw_data,
            reddit_data.get("cn", {}), global_news, date_str,
        )] = "cn"
        futs[pool.submit(
            analyze_intl, rss_data, reddit_data,
            global_news, hackernews or [], date_str,
        )] = "intl"

        for fut in as_completed(futs):
            key = futs[fut]
            try:
                text = fut.result()
                if text:
                    results[key] = text
            except Exception as e:
                log.error("分析 %s 失败: %s", key, e)
    return results
