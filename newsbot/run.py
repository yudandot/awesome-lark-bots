# -*- coding: utf-8 -*-
"""
早知天下事 — 主流程编排。

完整流程：
  1. 并行采集所有数据源（~30-60s）
  2. 并行 AI 分析（~2-3min）
  3. 格式化输出为 Markdown
  4. 保存到本地文件

用法：
  python3 -m newsbot.run                # 生成完整日报
  python3 -m newsbot.run --region cn    # 只生成华人圈
  python3 -m newsbot.run --no-ai        # 只采集原始数据，不做 AI 分析
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from newsbot.config import BEIJING, REPORTS_DIR, COLLECTOR_WORKERS, log
from newsbot.collectors.cn_trending import fetch_all_cn_trending, fetch_xiaohongshu_trending
from newsbot.collectors.hk_tw import fetch_all_hk_tw
from newsbot.collectors.international import fetch_all_international, fetch_google_news, fetch_hackernews
from newsbot.collectors.social import fetch_reddit_for_region, fetch_global_news, fetch_hackernews as fetch_hn
from newsbot.analyzer import run_all_analysis
from newsbot.formatter import format_full_report


def _extract_seed_keywords(cn_trending: dict[str, list[dict]], top_n: int = 5) -> list[str]:
    """从中国平台热榜中提取高频关键词，用于小红书搜索。"""
    titles: list[str] = []
    for items in cn_trending.values():
        for item in items[:5]:
            titles.append(item["title"])
    keywords: list[str] = []
    for title in titles[:top_n]:
        short = title[:10].strip()
        if short and len(short) >= 2:
            keywords.append(short)
    return keywords or ["今日热点", "热搜"]


def collect_all(regions: list[str] | None = None) -> dict:
    """
    并行采集所有数据源。
    返回包含所有原始数据的字典。
    """
    t0 = time.time()
    target_regions = regions or ["cn", "vn", "asia", "west"]

    results: dict = {
        "cn_trending": {},
        "xiaohongshu": [],
        "hk_tw": {},
        "rss": {},
        "reddit": {},
        "global_news": [],
        "hackernews": [],
    }

    with ThreadPoolExecutor(max_workers=COLLECTOR_WORKERS) as pool:
        futures = {}

        if "cn" in target_regions:
            futures[pool.submit(fetch_all_cn_trending)] = "cn_trending"
            futures[pool.submit(fetch_all_hk_tw)] = "hk_tw"
            futures[pool.submit(fetch_reddit_for_region, "cn")] = "reddit_cn"
            futures[pool.submit(fetch_global_news)] = "global_news"
            futures[pool.submit(fetch_hn)] = "hackernews"

        if any(r in target_regions for r in ("vn", "asia", "west")):
            futures[pool.submit(fetch_all_international)] = "rss"

        if "asia" in target_regions:
            futures[pool.submit(fetch_reddit_for_region, "asia")] = "reddit_asia"
        if "west" in target_regions:
            futures[pool.submit(fetch_reddit_for_region, "west")] = "reddit_west"

        for fut in as_completed(futures):
            key = futures[fut]
            try:
                data = fut.result()
                if key == "cn_trending":
                    results["cn_trending"] = data
                elif key == "hk_tw":
                    results["hk_tw"] = data
                elif key == "rss":
                    results["rss"] = data
                elif key == "reddit_cn":
                    results["reddit"]["cn"] = data
                elif key == "reddit_asia":
                    results["reddit"]["asia"] = data
                elif key == "reddit_west":
                    results["reddit"]["west"] = data
                elif key == "global_news":
                    results["global_news"] = data
                elif key == "hackernews":
                    results["hackernews"] = data
                log.info("采集完成: %s", key)
            except Exception as e:
                log.error("采集 %s 失败: %s", key, e)

    # 小红书（需要种子关键词，串行）
    if "cn" in target_regions and results["cn_trending"]:
        seed_kw = _extract_seed_keywords(results["cn_trending"])
        try:
            results["xiaohongshu"] = fetch_xiaohongshu_trending(seed_kw)
        except Exception as e:
            log.error("小红书采集失败: %s", e)

    elapsed = time.time() - t0
    total_items = sum(
        len(items) for platform_data in results.values()
        if isinstance(platform_data, dict)
        for items in (platform_data.values() if isinstance(platform_data, dict) else [])
        if isinstance(items, list)
    )
    log.info("=== 全部采集完成: %.1fs ===", elapsed)
    return results


def generate_report(
    regions: list[str] | None = None,
    with_ai: bool = True,
) -> tuple[str, Path]:
    """
    生成完整日报。

    Returns:
        (markdown_text, saved_file_path)
    """
    now = datetime.now(BEIJING)
    date_str = now.strftime("%Y年%m月%d日")
    file_date = now.strftime("%Y%m%d_%H%M")

    log.info("=" * 60)
    log.info("早知天下事日报生成 — %s", date_str)
    log.info("=" * 60)

    # 1. 采集
    log.info("Phase 1: 数据采集...")
    raw_data = collect_all(regions)

    # 2. AI 分析
    ai_results: dict[str, str] = {}
    if with_ai:
        log.info("Phase 2: AI 分析...")
        t0 = time.time()
        ai_results = run_all_analysis(
            cn_trending=raw_data["cn_trending"],
            hk_tw_data=raw_data["hk_tw"],
            reddit_data=raw_data["reddit"],
            global_news=raw_data["global_news"],
            rss_data=raw_data["rss"],
            date_str=date_str,
            hackernews=raw_data.get("hackernews", []),
        )
        log.info("AI 分析完成: %.1fs, %d 个区域", time.time() - t0, len(ai_results))
    else:
        log.info("Phase 2: 跳过 AI 分析 (--no-ai)")

    # 2.5 翻译外语 RSS 标题
    if with_ai:
        log.info("Phase 2.5: 翻译外语标题...")
        t0 = time.time()
        from newsbot.translate import translate_rss_titles
        # RSS: {region: {source: [items]}} — 逐 region 翻译
        for _rk, region_sources in raw_data["rss"].items():
            if region_sources:
                translate_rss_titles(region_sources)
        # Google News Global
        if raw_data.get("global_news"):
            translate_rss_titles({"Global": raw_data["global_news"]})
        # Hacker News
        if raw_data.get("hackernews"):
            translate_rss_titles({"HN": raw_data["hackernews"]})
        # Reddit: {region: {subreddit: [items]}}
        for _rk, sub_data in raw_data["reddit"].items():
            if sub_data:
                translate_rss_titles(sub_data)
        # 港台 Google News
        for k in list(raw_data["hk_tw"].keys()):
            if "Google News" in k:
                translate_rss_titles({k: raw_data["hk_tw"][k]})
        log.info("翻译完成: %.1fs", time.time() - t0)

    # 3. 格式化
    log.info("Phase 3: 格式化输出...")
    report = format_full_report(
        date_str=date_str,
        ai_results=ai_results,
        cn_trending=raw_data["cn_trending"],
        hk_tw_data=raw_data["hk_tw"],
        xiaohongshu=raw_data["xiaohongshu"],
        reddit_data=raw_data["reddit"],
        rss_data=raw_data["rss"],
        global_news=raw_data.get("global_news", []),
        hackernews=raw_data.get("hackernews", []),
    )

    # 4. 保存
    file_path = REPORTS_DIR / f"daily_digest_{file_date}.md"
    file_path.write_text(report, encoding="utf-8")
    log.info("日报已保存: %s (%d 字)", file_path, len(report))

    return report, file_path


def main():
    parser = argparse.ArgumentParser(description="早知天下事 — 全球热点日报生成器")
    parser.add_argument(
        "--region", nargs="*", default=None,
        choices=["cn", "vn", "asia", "west"],
        help="指定区域（不填=全部）",
    )
    parser.add_argument(
        "--no-ai", action="store_true",
        help="跳过 AI 分析，只采集原始数据",
    )
    args = parser.parse_args()

    report, path = generate_report(
        regions=args.region,
        with_ai=not args.no_ai,
    )
    print(f"\n✅ 日报已生成: {path}")
    print(f"   共 {len(report)} 字")


if __name__ == "__main__":
    main()
