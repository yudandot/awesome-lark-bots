# -*- coding: utf-8 -*-
"""
营销日历技能 — 节假日、电商节点、季节性选题。

让 idea_engine 和 planner 在构思阶段知道"最近什么节点可以蹭"，
而不是凭感觉选题。

数据来源：skills/calendar_data.yaml
更新方式：每年初更新一次，或随时添加品牌专属节点。
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from skills import Skill, register

CALENDAR_PATH = Path(__file__).parent / "calendar_data.yaml"


class CalendarSkill(Skill):
    name = "calendar"
    description = "营销日历 — 节假日、电商大促、季节性选题节点"
    trigger_keywords = ["日历", "节日", "节点", "排期", "什么时候发", "选题", "calendar"]
    bot_types = ["planner", "conductor"]

    def __init__(self, path: Optional[Path] = None):
        self.path = path or CALENDAR_PATH
        self._cache: Optional[dict] = None

    def _load(self) -> dict:
        if self._cache:
            return self._cache
        if not self.path.exists():
            return {}
        try:
            import yaml
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            self._cache = data if isinstance(data, dict) else {}
            return self._cache
        except Exception:
            return {}

    def should_activate(self, user_text: str, bot_type: str = "", **kwargs) -> bool:
        if not self.path.exists():
            return False
        if bot_type in self.bot_types:
            return True
        lower = user_text.lower()
        return any(kw.lower() in lower for kw in self.trigger_keywords)

    def get_context(self, **kwargs) -> str:
        data = self._load()
        if not data:
            return ""

        today = datetime.date.today()
        lookahead = int(kwargs.get("lookahead_days", 30))
        end = today + datetime.timedelta(days=lookahead)

        events = data.get("events", [])
        upcoming = []
        for ev in events:
            date_str = ev.get("date", "")
            try:
                ev_date = datetime.date.fromisoformat(date_str)
            except (ValueError, TypeError):
                if isinstance(date_str, str) and len(date_str) == 5:
                    try:
                        ev_date = datetime.date.fromisoformat(f"{today.year}-{date_str}")
                    except ValueError:
                        continue
                else:
                    continue

            if today <= ev_date <= end:
                days_left = (ev_date - today).days
                upcoming.append((ev_date, days_left, ev))

        season = data.get("seasons", {})
        month_key = str(today.month)
        seasonal_themes = season.get(month_key, [])

        if not upcoming and not seasonal_themes:
            return ""

        parts = [f"[营销日历 — {today.isoformat()} 起 {lookahead} 天]"]

        if upcoming:
            upcoming.sort(key=lambda x: x[0])
            parts.append("\n即将到来的节点：")
            for ev_date, days_left, ev in upcoming[:10]:
                name = ev.get("name", "")
                tip = ev.get("tip", "")
                prep = ev.get("prep_days", 0)
                tag = ""
                if days_left == 0:
                    tag = "📍 今天"
                elif days_left <= 3:
                    tag = f"⚡ {days_left}天后"
                elif prep and days_left <= prep:
                    tag = f"🔔 该准备了（{days_left}天后）"
                else:
                    tag = f"{days_left}天后"
                line = f"  {ev_date.strftime('%m/%d')} {name} [{tag}]"
                if tip:
                    line += f" — {tip}"
                parts.append(line)

        if seasonal_themes:
            parts.append(f"\n{today.month}月季节性选题方向：")
            for theme in seasonal_themes:
                if isinstance(theme, dict):
                    parts.append(f"  - {theme.get('name', '')}: {theme.get('tip', '')}")
                else:
                    parts.append(f"  - {theme}")

        return "\n".join(parts)


register(CalendarSkill())
