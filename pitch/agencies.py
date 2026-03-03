# -*- coding: utf-8 -*-
"""
Agency 定义与组队逻辑。
========================

- Agency 数据类：名称 + 人设 prompt + 颜色/emoji 标识
- DEFAULT_AGENCIES：体验派 / 增长派 / 品牌派
- parse_agency_spec()：解析用户自定义组队语法
  例如：「比稿 2组 体验派 增长派：活动主题」
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from pitch.prompts import (
    AGENCY_EXPERIENCE,
    AGENCY_GROWTH,
    AGENCY_BRAND,
    AGENCY_STYLES,
)

# ---------------------------------------------------------------------------
# Agency 数据类
# ---------------------------------------------------------------------------

@dataclass
class Agency:
    name: str
    system_prompt: str
    emoji: str = "🏢"
    color: str = "blue"


# ---------------------------------------------------------------------------
# 默认 3 个 Agency
# ---------------------------------------------------------------------------

DEFAULT_AGENCIES: List[Agency] = [
    Agency(
        name="体验派 Agency",
        system_prompt=AGENCY_EXPERIENCE,
        emoji="🎭",
        color="purple",
    ),
    Agency(
        name="增长派 Agency",
        system_prompt=AGENCY_GROWTH,
        emoji="📈",
        color="green",
    ),
    Agency(
        name="品牌派 Agency",
        system_prompt=AGENCY_BRAND,
        emoji="💎",
        color="orange",
    ),
]


# ---------------------------------------------------------------------------
# 用户自定义组队解析
# ---------------------------------------------------------------------------

_STYLE_ALIASES: dict[str, str] = {
    "体验": "体验派",
    "增长": "增长派",
    "品牌": "品牌派",
    "数据": "增长派",
    "data": "growth",
    "exp": "experience",
    "branding": "brand",
}


def _resolve_style(token: str) -> Optional[str]:
    """将用户输入的风格名称统一为 AGENCY_STYLES 中的 key。"""
    t = token.strip().lower()
    if t in AGENCY_STYLES:
        return t
    for alias, canonical in _STYLE_ALIASES.items():
        if alias in t:
            return canonical
    return None


_EMOJI_POOL = ["🎭", "📈", "💎", "🔥", "🚀", "🎯", "⚡", "🌊"]
_COLOR_POOL = ["purple", "green", "orange", "red", "blue", "indigo", "teal", "yellow"]


# 带冒号的前缀：剥掉后整段都当 topic，不再在正文里找冒号分割（避免需求里的「计划：」「目标：」等被误拆）
_TOPIC_ONLY_PREFIXES = ("比稿：", "比稿:", "pitch：", "pitch:")


def parse_agency_spec(raw_text: str) -> tuple[List[Agency], str]:
    """
    解析用户输入的比稿指令，提取 Agency 配置和话题。

    支持的格式：
      比稿：活动主题（可多行、可含冒号）  → 默认 3 组，整段为 topic
      比稿 2组 体验派 增长派：主题        → 自定义 2 组
      比稿 体验派 品牌派：主题            → 自定义 2 组（不写数量）
      pitch: topic（可多行）              → 默认 3 组
      pitch 2 growth brand: topic         → 自定义

    返回 (agencies, topic)。
    """
    text = raw_text.strip()

    # 长前缀优先，避免「比稿：」被当成「比稿」只剥掉两个字
    prefixes = ["比稿：", "比稿:", "比稿 ", "pitch：", "pitch:", "pitch ", "比稿", "pitch"]
    matched_prefix = ""
    for p in prefixes:
        if text.lower().startswith(p.lower()):
            matched_prefix = p
            text = text[len(p):].strip()
            break

    # 若用的是「比稿：」「pitch：」等，剥掉后整段都是 topic，不再按冒号拆（需求里可能有多处冒号）
    if matched_prefix in _TOPIC_ONLY_PREFIXES:
        spec_part = ""
        topic = text
    else:
        sep_match = re.search(r"[：:]", text)
        if sep_match:
            spec_part = text[:sep_match.start()].strip()
            topic = text[sep_match.end():].strip()
        else:
            spec_part = ""
            topic = text

    if not spec_part:
        return list(DEFAULT_AGENCIES), topic

    tokens = spec_part.split()

    num_groups = None
    style_tokens: list[str] = []
    for tok in tokens:
        m = re.match(r"^(\d+)\s*组?$", tok)
        if m:
            num_groups = int(m.group(1))
        else:
            resolved = _resolve_style(tok)
            if resolved:
                style_tokens.append(resolved)

    if not style_tokens:
        n = num_groups or 3
        return list(DEFAULT_AGENCIES[:n]), topic

    agencies: List[Agency] = []
    for i, style_key in enumerate(style_tokens):
        prompt = AGENCY_STYLES[style_key]
        zh_names = {"体验派": "体验派", "增长派": "增长派", "品牌派": "品牌派",
                     "experience": "体验派", "growth": "增长派", "brand": "品牌派"}
        name = zh_names.get(style_key, style_key) + " Agency"
        agencies.append(Agency(
            name=name,
            system_prompt=prompt,
            emoji=_EMOJI_POOL[i % len(_EMOJI_POOL)],
            color=_COLOR_POOL[i % len(_COLOR_POOL)],
        ))

    if num_groups and len(agencies) < num_groups:
        remaining = [a for a in DEFAULT_AGENCIES if a.name not in {ag.name for ag in agencies}]
        while len(agencies) < num_groups and remaining:
            agencies.append(remaining.pop(0))

    return agencies, topic
