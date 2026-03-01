# -*- coding: utf-8 -*-
"""
Stage 6: 复盘 — 采集效果数据，生成改进建议。
"""
from __future__ import annotations

from typing import Optional

from conductor.config import Platform, log
from conductor.models import ReviewReport


def generate_review(
    platform: Platform,
    post_id: str,
    brand: str = "",
) -> Optional[ReviewReport]:
    """采集发布效果并生成复盘报告（需要内容已发布一段时间）。"""
    log.info("复盘: %s post=%s (功能开发中)", platform.value, post_id)
    return None
