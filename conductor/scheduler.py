# -*- coding: utf-8 -*-
"""
定时调度器 — 自动扫描热点、定时选题生成内容、定时发布、定时互动。

调度规则：
  - 每日 scan_cron 时间扫描热点并自动选题 → 生成内容 → 待审批或自动发布
  - 每 30 分钟检查定时发布队列，到点则发布
  - 可选：飞书 Webhook 通知「有新内容待审批」
"""
from __future__ import annotations

import os
import threading
import time

import schedule

from conductor.config import (
    ScheduleConfig, load_schedule_config, load_safety_config,
    get_scan_times, Platform, log,
)
from conductor.store import store


def run_check_scheduled_posts() -> int:
    """
    检查定时发布队列，到点则发布。供本进程定时器或外部 HTTP 触发（如电脑休眠时由云端 cron 调用）。
    返回：本次发布的条数。
    """
    due_items = store.get_due_items()
    if not due_items:
        return 0
    log.info("发现 %d 条到时间的定时内容", len(due_items))
    count = 0
    for item in due_items:
        log.info("定时发布: %s [%s]", item.content_id, item.title[:30])
        for platform in item.target_platforms:
            try:
                from conductor.stages.publisher import publish_content
                result = publish_content(item.content_id, platform)
                if result.success:
                    log.info("定时发布成功: %s → %s", item.content_id, platform)
                    count += 1
                else:
                    log.warning("定时发布失败: %s → %s: %s", item.content_id, platform, result.error)
            except NotImplementedError:
                store.mark_published(item.content_id, platform, "")
                log.info("定时发布（标记完成）: %s → %s", item.content_id, platform)
                count += 1
            except Exception as e:
                log.error("定时发布异常: %s → %s: %s", item.content_id, platform, e)
    return count


def run_scheduled_scan_and_create() -> bool:
    """
    定时选题+生成：扫描热点 → 选题 → 生成内容 → 存草稿或自动发布。供本进程定时器或外部 HTTP 触发。
    返回：是否执行成功（无异常）。
    """
    from conductor.pipeline import run_pipeline
    from conductor.stages.trend_scanner import scan_trends
    from conductor.config import load_persona_defaults

    log.info("定时选题：开始扫描热点并生成内容")
    try:
        brand = os.getenv("CONDUCTOR_SCHEDULE_BRAND", "").strip() or os.getenv("CONDUCTOR_DEFAULT_BRAND", "").strip()
        platforms_str = os.getenv("CONDUCTOR_SCHEDULE_PLATFORMS", "xiaohongshu").strip()
        platforms = [p.strip() for p in platforms_str.split(",") if p.strip()]
        keywords_str = os.getenv("CONDUCTOR_SCHEDULE_TOPIC_KEYWORDS", "").strip()
        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

        plat_list = [Platform.from_str(p) for p in platforms]
        plat_list = [p for p in plat_list if p]
        if not plat_list:
            plat_list = [Platform.XIAOHONGSHU]

        trends = scan_trends([p.value for p in plat_list], topic_hint="")
        if not trends:
            topic = keywords[0] if keywords else "今日热点内容"
        elif keywords:
            topic = None
            for t in trends:
                if any(kw in (t.title or "") for kw in keywords):
                    topic = t.title
                    break
            topic = topic or trends[0].title
        else:
            topic = trends[0].title

        persona, target_audience, content_goals = load_persona_defaults()
        auto_publish = os.getenv("CONDUCTOR_AUTO_PUBLISH", "").lower() in ("1", "true", "yes")
        deep_mode = os.getenv("CONDUCTOR_ALWAYS_USE_BRAINSTORM", "").lower() in ("1", "true", "yes")
        safety = load_safety_config()

        run = run_pipeline(
            topic=topic[:100],
            brand=brand,
            platforms=platforms,
            persona=persona,
            target_audience=target_audience,
            content_goals=content_goals,
            auto_publish=auto_publish,
            deep_mode=deep_mode,
        )

        if run.status == "completed" and run.publish_results:
            content_id = run.publish_results[0].post_id
            if safety.require_human_approval and content_id:
                webhook = os.getenv("CONDUCTOR_NOTIFY_WEBHOOK", "").strip()
                if webhook:
                    try:
                        import requests
                        title = run.draft.idea.title if run.draft and run.draft.idea else topic[:30]
                        card = {
                            "header": {"title": {"content": "📋 有新内容待审批", "tag": "plain_text"}, "template": "orange"},
                            "elements": [
                                {"tag": "markdown", "content": f"**选题：**{topic[:80]}\n**标题：**{title[:60]}\n**内容ID：**`{content_id}`"},
                                {"tag": "note", "elements": [{"tag": "plain_text", "content": "在飞书对自媒体助手发送「详情 " + content_id + "」查看；发送「发布 " + content_id + "」审批；发送「自动发布 " + content_id + " 小红书」直接发布"}]},
                            ],
                        }
                        body = {"msg_type": "interactive", "card": card}
                        requests.post(webhook, json=body, timeout=10)
                    except Exception as e:
                        log.warning("定时任务：飞书通知失败 %s", e)
        elif run.error:
            log.warning("定时选题生成失败: %s", run.error)
        return True
    except Exception as e:
        log.error("定时选题异常: %s", e, exc_info=True)
        return False


class Scheduler:
    """内容调度器。"""

    def __init__(self, config: ScheduleConfig | None = None):
        self.config = config or load_schedule_config()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        """启动后台调度线程。"""
        if not self.config.enabled:
            log.info("调度器未启用（设置 CONDUCTOR_SCHEDULE_ENABLED=true 开启）")
            return

        self._running = True

        # 定时发布：每 30 分钟检查是否有到点的内容
        schedule.every(30).minutes.do(self._check_scheduled_posts)

        # 定时选题+生成：每日在配置的多个时间点各跑一次
        scan_times = get_scan_times()
        for t in scan_times:
            schedule.every().day.at(t).do(self._run_scheduled_scan_and_create)
        log.info("调度器已启动（每日 %s 定时选题生成，每 30 分钟检查定时发布）", ", ".join(scan_times))

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        schedule.clear()

    def _loop(self):
        while self._running:
            schedule.run_pending()
            time.sleep(10)

    def _run_scheduled_scan_and_create(self):
        run_scheduled_scan_and_create()

    def _check_scheduled_posts(self):
        run_check_scheduled_posts()
