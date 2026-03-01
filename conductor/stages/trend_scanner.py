# -*- coding: utf-8 -*-
"""
Stage 1: 感知 — 扫描各平台热点趋势。

数据来源（按优先级）：
  1. newsbot 采集器（最快、最全）
  2. JustOneAPI 搜索
  3. LLM 补充分析
"""
from __future__ import annotations

import os
import time

import requests

from conductor.config import log
from conductor.models import TrendItem

try:
    from newsbot.collectors.cn_trending import fetch_all_cn_trending
    _HAS_NEWSBOT = True
except ImportError:
    _HAS_NEWSBOT = False


def _fetch_via_joa(platform: str, keyword: str = "", max_items: int = 20) -> list[dict]:
    """通过 JustOneAPI 搜索。"""
    token = os.getenv("JOA_TOKEN", "").strip()
    base = os.getenv("JOA_BASE_URL", "http://localhost:30015").strip().rstrip("/")
    if not token:
        return []

    endpoint_map = {
        "weibo": "/weibo/search",
        "douyin": "/douyin/search/video",
        "xiaohongshu": "/xiaohongshu/search/note",
        "bilibili": "/bilibili/search/video",
        "kuaishou": "/kuaishou/search/video",
        "zhihu": "/zhihu/search",
    }
    endpoint = endpoint_map.get(platform)
    if not endpoint:
        return []

    try:
        resp = requests.get(
            f"{base}{endpoint}",
            params={"keyword": keyword or "热门", "token": token, "limit": max_items},
            timeout=30,
        )
        if resp.ok:
            data = resp.json()
            return data.get("data", data.get("items", []))[:max_items]
    except Exception as e:
        log.warning("JOA 搜索 %s 失败: %s", platform, e)
    return []


def scan_trends(
    platforms: list[str],
    topic_hint: str = "",
    max_per_platform: int = 15,
) -> list[TrendItem]:
    """
    扫描热点趋势，返回 TrendItem 列表。

    策略：先用 newsbot 获取热榜 → 回退到 JOA → 按 topic 补充搜索。
    """
    all_trends: list[TrendItem] = []

    if _HAS_NEWSBOT:
        try:
            cn_data = fetch_all_cn_trending()
            for plat_name, items in cn_data.items():
                normalized = plat_name.lower().replace("_trending", "")
                if normalized in platforms or not platforms:
                    for item in items[:max_per_platform]:
                        all_trends.append(TrendItem(
                            platform=normalized,
                            title=item.get("title", "")[:200],
                            heat=str(item.get("heat", "")),
                            url=item.get("url", ""),
                            timestamp=time.time(),
                        ))
            if all_trends:
                log.info("从 newsbot 获取 %d 条热榜", len(all_trends))
        except Exception as e:
            log.warning("newsbot 热榜采集失败: %s", e)

    if not all_trends:
        for platform in platforms:
            raw = _fetch_via_joa(platform, keyword=topic_hint or "热门", max_items=max_per_platform)
            for item in raw:
                title = item.get("title") or item.get("desc") or item.get("content", "")
                if title:
                    all_trends.append(TrendItem(
                        platform=platform, title=str(title)[:200],
                        heat=str(item.get("heat", item.get("hot_value", ""))),
                        url=str(item.get("url", "")), timestamp=time.time(),
                    ))

    if topic_hint:
        for platform in platforms[:3]:
            raw = _fetch_via_joa(platform, keyword=topic_hint, max_items=10)
            for item in raw:
                title = item.get("title") or item.get("desc") or ""
                if title:
                    all_trends.append(TrendItem(
                        platform=platform, title=str(title)[:200],
                        heat=str(item.get("heat", "")),
                        url=str(item.get("url", "")), timestamp=time.time(),
                    ))

    log.info("共扫描到 %d 条趋势", len(all_trends))
    return all_trends
