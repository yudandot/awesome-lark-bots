# -*- coding: utf-8 -*-
"""
Stage 5: 互动 — 监控评论并生成回复。

通过 JOA / MCP 工具采集已发布内容的评论，
用 LLM 生成符合品牌调性的回复。
"""
from __future__ import annotations

from core.llm import chat_completion
from conductor.config import Platform, log
from conductor.models import EngageAction


REPLY_SYSTEM = """你是一个社交媒体运营专家，负责回复用户评论。

回复要求：
1. 语气亲切自然，像真人在聊天
2. 回复简短（1-2句话），不要长篇大论
3. 积极正面，遇到负面评论也要温和化解
4. 适当使用 emoji，但不要过度
5. 如果评论是问题，尽量给出有用回答
6. 不要千篇一律——每条回复都要针对评论内容定制

只输出回复文本，不要加前缀或解释。"""


def check_and_reply(
    platform: Platform,
    post_id: str,
    brand: str = "",
    max_replies: int = 10,
) -> list[EngageAction]:
    """检查评论并生成回复（暂存，不自动发送）。"""
    actions: list[EngageAction] = []
    log.info("互动检查: %s post=%s (功能开发中)", platform.value, post_id)
    return actions


def generate_reply(comment_text: str, brand: str = "", context: str = "") -> str:
    """为单条评论生成回复。"""
    prompt = f"评论：{comment_text}"
    if brand:
        prompt += f"\n品牌：{brand}"
    if context:
        prompt += f"\n内容背景：{context[:200]}"
    prompt += "\n\n请生成一条合适的回复。"

    try:
        from core.skill_router import enrich_prompt
        enriched_system = enrich_prompt(REPLY_SYSTEM, user_text=prompt, bot_type="conductor")
        return chat_completion(provider="deepseek", system=enriched_system, user=prompt, temperature=0.8)
    except Exception as e:
        log.error("生成回复失败: %s", e)
        return ""
