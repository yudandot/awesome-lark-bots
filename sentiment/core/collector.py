# -*- coding: utf-8 -*-
"""
数据采集模块 — 统一搜索 + 分平台深度搜索 + Browser MCP 补充。
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests

from sentiment.config.settings import (
    JOA_TOKEN, BEIJING, REQ_DELAY, WORKERS,
    UNIFIED_MAX_PAGES, PLATFORM_MAX_PAGES, PLATFORM_PAGES_DEEP,
    BROWSER_MCP_HTTP_URL, CACHE_DIR, log,
)
from sentiment.core.joa_client import joa_request
from sentiment.core.platforms import (
    extract_items, parse_post, dedup_posts, filter_raw_by_time,
)


# ---------------------------------------------------------------------------
# 时间范围
# ---------------------------------------------------------------------------

def range_for_days(days: int):
    now = datetime.now(BEIJING)
    end_dt = (now - timedelta(days=1)).replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    start_dt = (now - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start_dt, end_dt


# ---------------------------------------------------------------------------
# Phase 1 — Unified Search
# ---------------------------------------------------------------------------

def _unified_one_kw(kw, start_s, end_s):
    items, cursor = [], None
    use_time_filter = True
    for page_num in range(UNIFIED_MAX_PAGES):
        p = {"keyword": kw, "source": "ALL"}
        if use_time_filter:
            p["start"], p["end"] = start_s, end_s
        if cursor:
            p["nextCursor"] = cursor
        d = joa_request("/api/search/v1", p)
        batch = extract_items(d)
        if page_num == 0 and use_time_filter and not batch:
            use_time_filter = False
            p = {"keyword": kw, "source": "ALL"}
            d = joa_request("/api/search/v1", p)
            batch = extract_items(d)
            if not batch:
                return []
            log.info("  unified [%s] 带时间无结果，已回退为不带时间请求", kw)
        if not batch:
            break
        items.extend(batch)
        cursor = d.get("nextCursor") if isinstance(d, dict) else None
        if not cursor:
            break
        time.sleep(REQ_DELAY)
    return items


# ---------------------------------------------------------------------------
# Phase 2 — Per-platform deep search
# ---------------------------------------------------------------------------

def _search_weibo(kw, start_dt, end_dt):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/weibo/search-all/v2", {
            "q": kw,
            "startDay": start_dt.strftime("%Y-%m-%d"), "startHour": 0,
            "endDay": end_dt.strftime("%Y-%m-%d"), "endHour": 23,
            "page": pg,
        })
        batch = extract_items(d, "weibo")
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "WEIBO")
    return items


def _search_douyin(kw):
    items = []
    search_id = None
    max_pg = PLATFORM_PAGES_DEEP.get("douyin", PLATFORM_MAX_PAGES)
    for pg in range(1, max_pg + 1):
        params = {
            "keyword": kw, "sortType": "_2", "publishTime": "_7",
            "duration": "_0", "page": pg,
        }
        if search_id:
            params["searchId"] = search_id
        d = joa_request("/api/douyin/search-video/v4", params)
        batch = extract_items(d, "douyin")
        if not batch:
            break
        items.extend(batch)
        if isinstance(d, dict):
            search_id = d.get("search_id") or d.get("searchId")
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "DOUYIN")
    return items


def _search_xhs(kw):
    items = []
    max_pg = PLATFORM_PAGES_DEEP.get("xiaohongshu", PLATFORM_MAX_PAGES)
    for pg in range(1, max_pg + 1):
        d = joa_request("/api/xiaohongshu/search-note/v2", {
            "keyword": kw, "page": pg,
            "sort": "time_descending", "noteType": "_0",
            "noteTime": "一周内",
        })
        batch = extract_items(d, "xiaohongshu")
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "XIAOHONGSHU")
    return items


def _search_bilibili(kw):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/bilibili/search-video/v2", {
            "keyword": kw, "page": pg, "order": "general",
        })
        batch = extract_items(d, "bilibili")
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "BILIBILI")
    return items


def _search_kuaishou(kw):
    items = []
    max_pg = PLATFORM_PAGES_DEEP.get("kuaishou", PLATFORM_MAX_PAGES)
    for pg in range(1, max_pg + 1):
        d = joa_request("/api/kuaishou/search-video/v2", {
            "keyword": kw, "page": pg,
        })
        batch = extract_items(d, "kuaishou")
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "KUAISHOU")
    return items


def _search_zhihu(kw):
    items = []
    for off in range(PLATFORM_MAX_PAGES):
        d = joa_request("/api/zhihu/search/v1", {"keyword": kw, "offset": off})
        batch = extract_items(d, "zhihu")
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "ZHIHU")
    return items


def _search_toutiao(kw):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/toutiao/search-content/v1", {"keyword": kw, "page": pg})
        batch = extract_items(d)
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "TOUTIAO")
    return items


def _search_weixin(kw):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/weixin/search-article/v1", {"keyword": kw, "page": pg})
        batch = extract_items(d)
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "WEIXIN")
    return items


def _search_tiktok(kw):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/tiktok/search-video/v2", {"keyword": kw, "page": pg})
        batch = extract_items(d)
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "TIKTOK")
    return items


def _search_youtube(kw):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/youtube/search-video/v1", {"keyword": kw, "page": pg})
        batch = extract_items(d)
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "YOUTUBE")
    return items


def _search_twitter(kw):
    items = []
    cursor = None
    for _ in range(PLATFORM_MAX_PAGES):
        params = {"keyword": kw}
        if cursor:
            params["nextCursor"] = cursor
        d = joa_request("/api/twitter/search/v1", params)
        batch = extract_items(d)
        if not batch:
            break
        items.extend(batch)
        cursor = d.get("nextCursor") if isinstance(d, dict) else None
        if not cursor:
            break
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "TWITTER")
    return items


def _search_instagram(kw):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/instagram/search/v1", {"keyword": kw, "page": pg})
        batch = extract_items(d)
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "INSTAGRAM")
    return items


def _search_facebook(kw):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/facebook/search/v1", {"keyword": kw, "page": pg})
        batch = extract_items(d)
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "FACEBOOK")
    return items


def _search_taobao(kw):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/taobao/search-item/v1", {"keyword": kw, "page": pg})
        batch = extract_items(d)
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "TAOBAO")
    return items


def _search_pinduoduo(kw):
    items = []
    for pg in range(1, PLATFORM_MAX_PAGES + 1):
        d = joa_request("/api/pinduoduo/search-item/v1", {"keyword": kw, "page": pg})
        batch = extract_items(d)
        if not batch:
            break
        items.extend(batch)
        time.sleep(REQ_DELAY)
    for it in items:
        if isinstance(it, dict):
            it.setdefault("source", "PINDUODUO")
    return items


PLATFORM_SEARCH_DISPATCH = {
    "weibo": lambda kw, s, e: _search_weibo(kw, s, e),
    "douyin": lambda kw, s, e: _search_douyin(kw),
    "xiaohongshu": lambda kw, s, e: _search_xhs(kw),
    "bilibili": lambda kw, s, e: _search_bilibili(kw),
    "kuaishou": lambda kw, s, e: _search_kuaishou(kw),
    "zhihu": lambda kw, s, e: _search_zhihu(kw),
    "toutiao": lambda kw, s, e: _search_toutiao(kw),
    "weixin": lambda kw, s, e: _search_weixin(kw),
    "tiktok": lambda kw, s, e: _search_tiktok(kw),
    "youtube": lambda kw, s, e: _search_youtube(kw),
    "twitter": lambda kw, s, e: _search_twitter(kw),
    "instagram": lambda kw, s, e: _search_instagram(kw),
    "facebook": lambda kw, s, e: _search_facebook(kw),
    "taobao": lambda kw, s, e: _search_taobao(kw),
    "pinduoduo": lambda kw, s, e: _search_pinduoduo(kw),
}

PLATFORMS_DEEP = list(PLATFORM_SEARCH_DISPATCH.keys())


def _per_platform(platform, kw, start_dt, end_dt):
    fn = PLATFORM_SEARCH_DISPATCH.get(platform)
    if fn:
        return fn(kw, start_dt, end_dt)
    return []


# ---------------------------------------------------------------------------
# Browser MCP 补充
# ---------------------------------------------------------------------------

def _load_browser_mcp_posts(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Browser MCP 文件加载失败 %s: %s", path, e)
        return []
    if not isinstance(data, list):
        data = data.get("posts", data.get("items", [])) if isinstance(data, dict) else []
    return [parse_post(r) for r in data if isinstance(r, dict)]


def _fetch_browser_mcp_http(profile: dict, start_s: str, end_s: str) -> list[dict]:
    url = BROWSER_MCP_HTTP_URL
    if not url:
        return []
    payload = {
        "keywords": profile.get("keywords", []),
        "start": start_s,
        "end": end_s,
        "profile_id": profile.get("id", ""),
        "days": profile.get("days", 7),
    }
    try:
        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("Browser MCP HTTP 请求失败: %s", e)
        return []
    raw = data.get("posts", data.get("items", data if isinstance(data, list) else []))
    if not isinstance(raw, list):
        return []
    return [p for p in (parse_post(x) for x in raw if isinstance(x, dict)) if p]


# ---------------------------------------------------------------------------
# Mock 数据（无 JOA_TOKEN 时使用）
# ---------------------------------------------------------------------------

def _mock_posts():
    return [
        {"platform": "微博", "title": "新品发布体验",
         "content": "新品的设计太棒了，包装精致质感满满，超出预期", "url": ""},
        {"platform": "小红书", "title": "品牌活动分享",
         "content": "参加了品牌线下快闪活动，互动体验非常好，推荐大家去", "url": ""},
        {"platform": "B站", "title": "新手入门教程",
         "content": "新手必看！手把手教你上手这款产品的所有功能", "url": ""},
        {"platform": "抖音", "title": "用户体验反馈",
         "content": "APP偶尔闪退，加载速度也有点慢，希望官方尽快优化", "url": ""},
        {"platform": "知乎", "title": "产品深度评测",
         "content": "价格偏高但品质不错，性价比见仁见智，老用户优惠太少", "url": ""},
        {"platform": "快手", "title": "开箱测评",
         "content": "收到新品开箱！包装设计很用心，产品质感一流", "url": ""},
        {"platform": "微博", "title": "售后服务反馈",
         "content": "客服响应慢，售后流程复杂，希望改进服务体验", "url": ""},
        {"platform": "B站", "title": "品牌联名评价",
         "content": "这次跨界联名设计很好看，但限定款定价偏高", "url": ""},
    ]


# ---------------------------------------------------------------------------
# 采集入口
# ---------------------------------------------------------------------------

def collect_posts(profile: dict, browser_posts_path: str | None = None,
                   platforms: list[str] | None = None) -> list[dict]:
    """
    完整采集流程：统一搜索 + 分平台 + Browser MCP 补充。

    Args:
        profile: 报告配置 dict
        browser_posts_path: Browser MCP 补充数据文件路径
        platforms: 指定平台列表（如 ["weibo", "douyin"]），None 则用默认全平台
    """
    keywords = profile["keywords"]
    max_posts = profile.get("max_posts", 5000)
    start_dt, end_dt = range_for_days(profile["days"])
    start_s = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_s = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    target_platforms = platforms or [p for p in PLATFORMS_DEEP if p in PLATFORM_SEARCH_DISPATCH]

    if not JOA_TOKEN:
        if profile.get("id") == "brand-weekly":
            log.error("JOA_TOKEN 未设置，品牌周报需真实采集，不生成报告")
            return []
        log.warning("JOA_TOKEN 未设置 — 使用模拟数据")
        return _mock_posts()

    log.info("=== 采集窗口: %s ~ %s (报告: %s) ===", start_s, end_s, profile["title"])
    log.info("目标平台: %s", target_platforms)
    all_raw: list[dict] = []
    skip_phase1 = profile.get("id") == "brand-weekly" or platforms is not None

    if not skip_phase1:
        log.info("Phase 1: 统一搜索 (%d 关键词 × 最多 %d 页)...",
                 len(keywords), UNIFIED_MAX_PAGES)
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = {
                pool.submit(_unified_one_kw, kw, start_s, end_s): kw
                for kw in keywords
            }
            for f in as_completed(futs):
                kw = futs[f]
                try:
                    items = f.result()
                    log.info("  unified [%s] → %d items", kw, len(items))
                    all_raw.extend(items)
                except Exception as exc:
                    log.warning("  unified [%s] error: %s", kw, exc)
        all_raw = filter_raw_by_time(all_raw, start_dt, end_dt)
        posts = dedup_posts([parse_post(r) for r in all_raw if isinstance(r, dict)])
        log.info("Phase 1 完成: %d 条（去重+时间过滤后）", len(posts))
    else:
        log.info("Phase 1: 跳过（直接分平台采集）")
        posts = []

    if len(posts) < max_posts:
        log.info("Phase 2: 分平台深度搜索 (%d 平台 × %d 关键词, 上限 %d 条)...",
                 len(target_platforms), len(keywords), max_posts)
        tasks = [(plat, kw) for kw in keywords for plat in target_platforms]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = {
                pool.submit(_per_platform, plat, kw, start_dt, end_dt): (plat, kw)
                for plat, kw in tasks
            }
            for f in as_completed(futs):
                plat, kw = futs[f]
                try:
                    items = f.result()
                    if items:
                        valid = [r for r in items if isinstance(r, dict)]
                        log.info("  %s [%s] → %d items", plat, kw, len(valid))
                        posts.extend(parse_post(r, plat) for r in valid)
                except Exception as exc:
                    if plat == "xiaohongshu":
                        log.warning("  小红书 [%s] 数据可能受限: %s", kw, exc)
                    else:
                        log.warning("  %s [%s] error: %s", plat, kw, exc)
                if len(posts) >= max_posts * 1.2:
                    log.info("  已达到上限附近 (%d/%d)，取消剩余任务", len(posts), max_posts)
                    for remaining in futs:
                        remaining.cancel()
                    break
        posts = dedup_posts(posts)
        log.info("Phase 2 完成: %d 条", len(posts))

    if browser_posts_path and os.path.isfile(browser_posts_path):
        extra = _load_browser_mcp_posts(browser_posts_path)
        if extra:
            posts.extend(extra)
            posts = dedup_posts(posts)
            log.info("Browser MCP 文件合并: +%d 条，去重后共 %d 条", len(extra), len(posts))
    if BROWSER_MCP_HTTP_URL:
        extra = _fetch_browser_mcp_http(profile, start_s, end_s)
        if extra:
            posts.extend(extra)
            posts = dedup_posts(posts)
            log.info("Browser MCP HTTP 合并: +%d 条，去重后共 %d 条", len(extra), len(posts))

    if len(posts) > max_posts:
        posts = posts[:max_posts]

    import re as _re
    _kw_tag = "_".join(keywords[:3])
    _kw_tag = _re.sub(r'[\\/:*?"<>|\s]+', '_', _kw_tag)[:30]
    cache_name = CACHE_DIR / f"cache_{_kw_tag}_{datetime.now(BEIJING).strftime('%Y%m%d_%H%M')}.json"
    try:
        with open(cache_name, "w", encoding="utf-8") as fp:
            json.dump(posts, fp, ensure_ascii=False)
        log.info("已缓存 %d 条 → %s", len(posts), cache_name)
    except OSError:
        pass

    if not posts and profile.get("id") == "brand-weekly":
        return []
    return posts if posts else _mock_posts()
