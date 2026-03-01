# -*- coding: utf-8 -*-
"""
自媒体助手配置 — 平台定义、调度参数、安全阈值。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger("conductor")
log.setLevel(logging.DEBUG)
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(name)s] %(levelname)s %(message)s"))
    log.addHandler(_h)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "conductor"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── 支持发布的平台 ─────────────────────────────────────────────

class Platform(str, Enum):
    WEIBO = "weibo"
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"
    BILIBILI = "bilibili"
    KUAISHOU = "kuaishou"
    ZHIHU = "zhihu"

    @classmethod
    def from_str(cls, s: str) -> Optional["Platform"]:
        aliases = {
            "微博": cls.WEIBO, "wb": cls.WEIBO,
            "抖音": cls.DOUYIN, "dy": cls.DOUYIN,
            "小红书": cls.XIAOHONGSHU, "xhs": cls.XIAOHONGSHU,
            "b站": cls.BILIBILI, "bilibili": cls.BILIBILI,
            "快手": cls.KUAISHOU, "ks": cls.KUAISHOU,
            "知乎": cls.ZHIHU, "zh": cls.ZHIHU,
        }
        return aliases.get(s.lower().strip()) or cls.__members__.get(s.upper())


# ── Pipeline 阶段 ─────────────────────────────────────────────

class Stage(str, Enum):
    SCAN = "scan"
    IDEATE = "ideate"
    CREATE = "create"
    PUBLISH = "publish"
    ENGAGE = "engage"
    REVIEW = "review"


# ── 单次任务配置 ──────────────────────────────────────────────

@dataclass
class TaskConfig:
    """一次完整的内容生产任务配置。"""
    topic: str = ""
    brand: str = ""
    target_platforms: list[Platform] = field(default_factory=lambda: [Platform.XIAOHONGSHU])
    content_type: str = "short_video"       # short_video / image_post / article
    auto_publish: bool = False              # 是否自动发布（False=仅生成草稿）
    auto_engage: bool = False               # 是否自动互动
    max_comments_per_post: int = 10         # 自动回复评论上限
    review_after_hours: int = 24            # 发布多少小时后复盘
    # 发帖人设与目标（可选，用于统一口吻和受众）
    persona: str = ""                       # 发帖人设：口吻、风格、身份感（如「治愈系旅行博主」）
    target_audience: str = ""               # 目标受众描述（如「18-30岁一二线女性」）
    content_goals: str = ""                 # 内容目标（如「涨粉、种草、品牌曝光」）


# ── 调度配置 ──────────────────────────────────────────────────

@dataclass
class ScheduleConfig:
    """定时自动运行配置。"""
    enabled: bool = False
    scan_cron: str = "0 8 * * *"            # 每天 8:00 扫描热点
    publish_cron: str = "0 10,15,20 * * *"  # 每天 10/15/20 点发布
    engage_cron: str = "*/30 * * * *"       # 每 30 分钟检查互动
    review_cron: str = "0 22 * * *"         # 每晚 22:00 复盘
    max_posts_per_day: int = 3              # 每日发布上限


# ── 安全配置 ──────────────────────────────────────────────────

@dataclass
class SafetyConfig:
    """内容安全审核配置。"""
    require_human_approval: bool = True     # 发布前是否需要人工审批
    sensitive_words: list[str] = field(default_factory=list)
    min_quality_score: float = 0.6          # AI 自评最低分（0-1）
    max_auto_replies_per_hour: int = 20     # 每小时自动回复上限


def load_schedule_config() -> ScheduleConfig:
    return ScheduleConfig(
        enabled=os.getenv("CONDUCTOR_SCHEDULE_ENABLED", "").lower() in ("1", "true", "yes"),
        max_posts_per_day=int(os.getenv("CONDUCTOR_MAX_POSTS_PER_DAY", "3")),
    )


def get_scan_time_from_cron(cron_expr: str = "0 8 * * *") -> str:
    """从 cron 表达式解析每日执行时间，返回 "HH:MM"。默认 08:00。"""
    parts = cron_expr.strip().split()
    if len(parts) >= 2:
        try:
            m, h = int(parts[0]), int(parts[1])
            return f"{h:02d}:{m:02d}"
        except ValueError:
            pass
    return "08:00"


def get_scan_times() -> list[str]:
    """
    返回每日定时选题的执行时间列表 "HH:MM"。
    优先读 CONDUCTOR_SCHEDULE_SCAN_TIMES（逗号分隔，如 08:00,12:00,19:00），
    否则默认 08:00。
    """
    raw = os.getenv("CONDUCTOR_SCHEDULE_SCAN_TIMES", "").strip()
    if raw:
        times = [t.strip() for t in raw.split(",") if t.strip()]
        if times:
            return times
    return ["08:00"]


def load_persona_defaults() -> tuple[str, str, str]:
    """从环境变量读取默认人设、目标受众、内容目标。支持 CONDUCTOR_PERSONA_FILE 从文件加载人设。"""
    persona_file = os.getenv("CONDUCTOR_PERSONA_FILE", "").strip()
    if persona_file:
        path = Path(persona_file)
        if not path.is_absolute():
            path = (DATA_DIR.parent.parent / persona_file) if persona_file.startswith("data/") else (DATA_DIR / persona_file)
        if path.exists():
            try:
                persona = path.read_text(encoding="utf-8").strip()
                # 注入 prompt 时避免过长，保留前 3200 字
                if len(persona) > 3200:
                    persona = persona[:3200] + "\n\n（人设说明已截断，请按上述风格执行）"
            except Exception as e:
                log.warning("读取人设文件失败 %s: %s", path, e)
                persona = os.getenv("CONDUCTOR_PERSONA", "").strip()
        else:
            persona = os.getenv("CONDUCTOR_PERSONA", "").strip()
    else:
        persona = os.getenv("CONDUCTOR_PERSONA", "").strip()
    return (
        persona,
        os.getenv("CONDUCTOR_TARGET_AUDIENCE", "").strip(),
        os.getenv("CONDUCTOR_CONTENT_GOALS", "").strip(),
    )


def load_safety_config() -> SafetyConfig:
    words_raw = os.getenv("CONDUCTOR_SENSITIVE_WORDS", "")
    words = [w.strip() for w in words_raw.split(",") if w.strip()]
    return SafetyConfig(
        # 默认直接发布（不存草稿）；设 CONDUCTOR_AUTO_PUBLISH=false 则只存草稿等审批
        require_human_approval=os.getenv("CONDUCTOR_AUTO_PUBLISH", "true").lower() not in ("1", "true", "yes"),
        sensitive_words=words,
    )
