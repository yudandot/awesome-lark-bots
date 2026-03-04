# -*- coding: utf-8 -*-
"""
技能路由器 — 自动判断当前对话需要哪些 skills，注入到 LLM prompt。

用法（任何 bot 都可以一行接入）：
  >>> from core.skill_router import enrich_prompt
  >>>
  >>> system = enrich_prompt(
  ...     base_prompt="你是备忘助手...",
  ...     user_text="帮我规划品牌推广日程",
  ...     bot_type="assistant",
  ... )
  >>> # system 现在包含自动注入的品牌知识和营销知识

设计原则：
  - 零配置：bot 只需调一行，router 自动决定加载什么
  - 可覆写：bot 也可以手动指定 skill_names 跳过自动检测
  - Token 安全：有 max_chars 限制，避免爆 prompt
  - 静默失败：任何 skill 加载出错都不会影响主流程
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("skill_router")

_MAX_SKILL_CHARS = 50000

_SKILL_PRIORITY = [
    "decision_frameworks", "thinking_models", "personal",
    "stakeholder", "cross_cultural", "translation",
    "brand", "platform", "copywriting", "calendar", "marketing",
    "video_prompt", "platform_adapter", "creative_brief", "brand_voice_checker",
]


def enrich_prompt(
    base_prompt: str,
    user_text: str = "",
    bot_type: str = "",
    skill_names: Optional[list[str]] = None,
    max_chars: int = _MAX_SKILL_CHARS,
    **skill_kwargs,
) -> str:
    """
    在 base_prompt 后追加自动激活的 skill 上下文。

    参数:
      base_prompt   — 原始 system prompt
      user_text     — 用户这条消息的内容（用于 skill 激活判断和上下文提取）
      bot_type      — 调用方机器人类型，如 "assistant" / "brainstorm" / "planner"
      skill_names   — 手动指定要加载的 skill 列表；为 None 时自动检测
      max_chars     — skill 上下文的总字符上限
      **skill_kwargs — 透传给 skill.get_context() 的额外参数
    """
    from skills import list_skills

    skills_to_load = []

    if skill_names is not None:
        from skills import get_skill
        for name in skill_names:
            s = get_skill(name)
            if s:
                skills_to_load.append(s)
    else:
        for s in list_skills():
            try:
                if s.should_activate(user_text, bot_type=bot_type, **skill_kwargs):
                    skills_to_load.append(s)
            except Exception:
                continue

    if not skills_to_load:
        return base_prompt

    def _sort_key(s):
        try:
            return _SKILL_PRIORITY.index(s.name)
        except ValueError:
            return len(_SKILL_PRIORITY)
    skills_to_load.sort(key=_sort_key)

    chunks = []
    total = 0
    for s in skills_to_load:
        try:
            kwargs = dict(skill_kwargs)
            if "detect_from" not in kwargs and user_text:
                kwargs["detect_from"] = user_text
            if "bot_type" not in kwargs and bot_type:
                kwargs["bot_type"] = bot_type
            ctx = s.get_context(**kwargs)
            if not ctx:
                continue
            if total + len(ctx) > max_chars:
                remaining = max_chars - total
                if remaining > 200:
                    ctx = ctx[:remaining] + "\n...(已截断)"
                else:
                    break
            chunks.append(ctx)
            total += len(ctx)
        except Exception as e:
            log.debug("skill %s 加载失败: %s", s.name, e)
            continue

    if not chunks:
        return base_prompt

    skill_block = "\n\n".join(chunks)
    return f"{base_prompt}\n\n━━ 以下为自动加载的领域知识（仅供参考）━━\n\n{skill_block}"
