# -*- coding: utf-8 -*-
"""
舆情采集主流程编排 —— 串联采集、统计、导出、上传的完整链路。
=========================================================

一次完整的采集流程：
  1. 采集(collect)  : 通过 JustOneAPI 从指定平台拉取帖子
  2. 统计(stats)    : 按平台、情感倾向统计数据
  3. 导出(export)   : 生成 JSON + Markdown 文件
  4. 上传(upload)   : (可选) 推送到 GitHub 仓库
  5. 分析(analyze)  : (可选) AI 生成分析报告

流程结果封装为 RunResult 对象返回，bot.py 将其格式化后回复用户。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sentiment.config.settings import log, ALL_PLATFORMS
from sentiment.config.profiles import get_profile
from sentiment.core.collector import collect_posts
from sentiment.core.stats import compute_stats
from sentiment.exporter import export_all, make_tag
from sentiment.github_client import upload_files, is_configured as github_configured


@dataclass
class RunResult:
    """采集运行结果。"""
    profile_id: str
    profile_title: str
    total_posts: int
    stats_summary: str
    local_files: dict[str, Path] = field(default_factory=dict)
    cloud_urls: dict[str, Optional[str]] = field(default_factory=dict)
    ai_report: str = ""
    elapsed_sec: float = 0.0
    error: str = ""


def _stats_summary(stats: dict) -> str:
    total = stats["total"]
    plat_parts = [f"{p}{c}条" for p, c in stats["platform"].most_common()]
    s = stats["sentiment"]
    total_or_1 = max(total, 1)
    return (
        f"共 {total} 条 | "
        f"{', '.join(plat_parts)} | "
        f"正面{s['正面']}({s['正面']/total_or_1*100:.0f}%) "
        f"中性{s['中性']}({s['中性']/total_or_1*100:.0f}%) "
        f"负面{s['负面']}({s['负面']/total_or_1*100:.0f}%)"
    )


def run_collect(
    profile_id: str = "brand-weekly",
    with_ai: bool = False,
    custom_keywords: list[str] | None = None,
    custom_platforms: list[str] | None = None,
    custom_days: int | None = None,
    custom_max_posts: int | None = None,
) -> RunResult:
    """
    执行一次完整采集+导出+推送。

    Args:
        profile_id: 报告类型 ID（预设报告）或 "custom"
        with_ai: 是否同时运行内置 AI 分析
        custom_keywords: 自定义关键词列表
        custom_platforms: 自定义平台列表
        custom_days: 自定义天数
        custom_max_posts: 自定义最大条数
    """
    if custom_keywords:
        profile = {
            "id": "custom",
            "title": f"自定义采集: {', '.join(custom_keywords[:3])}",
            "subject": custom_keywords[0],
            "keywords": custom_keywords,
            "days": custom_days or 7,
            "max_posts": custom_max_posts or 5000,
            "kimi_sample": 2000,
            "web_supplement": False,
            "_platforms": custom_platforms or [],
        }
    else:
        profile = get_profile(profile_id)
        overrides = {}
        if custom_days:
            overrides["days"] = custom_days
        if custom_max_posts:
            overrides["max_posts"] = custom_max_posts
        if custom_platforms:
            overrides["_platforms"] = custom_platforms
        if overrides:
            profile = {**profile, **overrides}

    result = RunResult(
        profile_id=profile.get("id", profile_id),
        profile_title=profile["title"],
        total_posts=0,
        stats_summary="",
    )
    t0 = time.time()

    try:
        log.info("=== [%s] 开始采集 ===", profile["title"])
        posts = collect_posts(profile, platforms=custom_platforms)
        result.total_posts = len(posts)
        if not posts:
            result.error = "采集到 0 条数据"
            result.elapsed_sec = time.time() - t0
            return result
        log.info("采集完成: %d 条 (%.1fs)", len(posts), time.time() - t0)

        stats = compute_stats(posts)
        result.stats_summary = _stats_summary(stats)
        log.info("统计完成: %s", result.stats_summary)

        file_paths = export_all(posts, stats, profile)
        result.local_files = file_paths
        log.info("导出完成: %s", {k: v.name for k, v in file_paths.items()})

        if github_configured():
            tag = make_tag(profile)
            cloud_urls = upload_files(file_paths, tag)
            result.cloud_urls = cloud_urls
            uploaded = sum(1 for u in cloud_urls.values() if u)
            log.info("GitHub 推送: %d/%d 文件", uploaded, len(cloud_urls))
        else:
            log.info("GitHub 未配置，跳过推送")

        if with_ai:
            from sentiment.core.analyzer import analyze_with_ai, kimi_web_search_supplement
            from concurrent.futures import ThreadPoolExecutor
            log.info("启动 AI 分析...")
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_web = pool.submit(kimi_web_search_supplement, profile)
                web_supplement = fut_web.result()
            ai_text = analyze_with_ai(posts, stats, profile, web_supplement)
            result.ai_report = ai_text
            log.info("AI 分析完成 (%d 字)", len(ai_text))

    except Exception as e:
        log.error("采集流程异常: %s", e, exc_info=True)
        result.error = str(e)

    result.elapsed_sec = time.time() - t0
    log.info("=== [%s] 完成 (%.1fs) ===", profile["title"], result.elapsed_sec)
    return result


def format_result_message(result: RunResult) -> str:
    """将 RunResult 格式化为飞书回复文本，附带下一步引导。"""
    if result.error:
        lines = [
            f"❌ 采集未成功: {result.error}",
            "",
            "你可以:",
            "  ➡️ 重新发送相同指令再试一次",
            "  ➡️ 换个关键词或平台试试",
            "  ➡️ 发送「状态」检查配置是否正常",
        ]
        return "\n".join(lines)

    lines = [
        f"✅ {result.profile_title} 采集完成！",
        f"⏱ 耗时 {result.elapsed_sec:.0f} 秒",
        "",
        f"📊 {result.stats_summary}",
    ]

    has_cloud = any(result.cloud_urls.values())
    if has_cloud:
        lines.append("")
        lines.append("📁 文件已上传到 GitHub:")
        for file_type, url in result.cloud_urls.items():
            if url:
                label = {"raw_json": "原始数据 (JSON)", "analysis_md": "分析材料 (Markdown)"}.get(file_type, file_type)
                lines.append(f"  • {label}")
                lines.append(f"    {url}")
    elif result.local_files:
        lines.append("")
        lines.append("📁 本地文件:")
        for file_type, path in result.local_files.items():
            label = {"raw_json": "原始数据 (JSON)", "analysis_md": "分析材料 (Markdown)"}.get(file_type, file_type)
            lines.append(f"  • {label}: {path.name}")

    if result.ai_report:
        lines.append("")
        lines.append("🤖 AI 分析报告已生成（详见文件）")

    lines.append("")
    lines.append("━━━ 接下来你可以 ━━━")
    if has_cloud:
        lines.append("  📎 复制上面的 GitHub 链接给 Claude Code 做深度分析")
    else:
        lines.append("  💡 .md 文件可直接粘贴到任意 AI 客户端做深度分析")
    lines.append("  🔄 发送新的采集指令继续采集")
    lines.append("  📋 发送「平台」查看更多可用平台")

    return "\n".join(lines)
