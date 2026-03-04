# -*- coding: utf-8 -*-
"""
Stage 2: 构思 — 脑暴或快速创意，产出内容方向。

两种模式：
  - 快速模式：用 AgentLoop + 工具产出创意（LLM 可主动搜索热点、查品牌、看竞品）
  - 深度模式：调用 brainstorm 五人团队脑暴 → 由 content_factory 调用 creative prompt 机器人生成给火山的需求
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from core.llm import chat_completion
from core.skill_router import enrich_prompt
from conductor.config import log
from conductor.models import TrendItem, ContentIdea


IDEATION_SYSTEM = """你是一位资深自媒体内容策划师，擅长结合热点做出有传播力的内容。

你拥有一系列工具。在产出创意之前，请务必：
1. 查 get_team_decisions — 了解团队之前的判断和偏好，避免重复被否决的方向
2. 查 list_past_content — 看过去做过什么，避免选题重复，了解什么有效
3. 如果用户指定了品牌 → 查 get_brand_info 获取品牌调性
4. 搜 search_platform — 在目标平台上搜索相关话题，看竞品/爆款怎么做的
5. 如果需要更多灵感 → 用 get_trending 看实时热搜，或 web_search 搜行业动态

基于以上调研结果，产出有爆款潜力的内容创意。

要求：
- 差异化：不能是人人都在做的视角，要有独特切口
- 钩子要具体到用户看到的第一句话/第一个画面
- 诚实评估吸引力分数（0-1），不要都打高分

最终输出严格 JSON（不要输出其他内容）：
{"ideas": [
  {
    "title": "内容标题",
    "angle": "独特切入角度（一句话）",
    "hook": "前3秒/第一行的钩子文案",
    "target_platform": "xiaohongshu/douyin/bilibili/weibo/zhihu",
    "content_type": "short_video/image_post/article",
    "estimated_appeal": 0.8,
    "reasoning": "为什么这个创意有爆款潜力（引用你调研到的具体数据/趋势/竞品分析）"
  }
]}

产出 5 个创意，按吸引力从高到低排列。"""


SELECTION_SYSTEM = """你是内容策略总监。从以下创意中选择最值得执行的一个。

评估维度：话题热度、差异化、可执行性、传播力。
返回 JSON：{"selected_index": 数字, "reason": "选择理由"}"""


def generate_ideas(
    trends: list[TrendItem],
    topic: str = "",
    brand: str = "",
    content_type: str = "short_video",
    target_platforms: Optional[list[str]] = None,
    persona: str = "",
    target_audience: str = "",
    content_goals: str = "",
) -> list[ContentIdea]:
    """用 AgentLoop + 工具产出内容创意。LLM 可主动搜索热点、查品牌、看竞品。"""
    from core.agent import AgentLoop
    from core.tools import (
        WEB_SEARCH_TOOL, TRENDING_TOOL, SEARCH_PLATFORM_TOOL,
        BRAND_INFO_TOOL, TEAM_DECISIONS_TOOL, PAST_CONTENT_TOOL,
    )

    trend_text = "\n".join(
        f"- [{t.platform}] {t.title} (热度:{t.heat})"
        for t in trends[:20]
    ) if trends else ""

    extra = []
    if persona:
        extra.append(f"发帖人设/口吻：{persona}")
    if target_audience:
        extra.append(f"目标受众：{target_audience}")
    if content_goals:
        extra.append(f"内容目标：{content_goals}")

    platforms_str = ", ".join(target_platforms or ["xiaohongshu"])
    user_prompt = f"""请为以下需求产出 5 个内容创意：

主题：{topic or '（未指定，请从热点中挖掘）'}
品牌：{brand or '（未指定）'}
内容形式偏好：{content_type}
目标平台：{platforms_str}
{chr(10).join(extra)}

{'已有热点数据（仅供参考，你可以用工具获取更多信息）：' + chr(10) + trend_text if trend_text else '请用 get_trending 工具查看当前热点。'}

请先用工具调研，再产出创意。最终输出 JSON。"""

    try:
        agent = AgentLoop(
            provider="deepseek",
            system=enrich_prompt(IDEATION_SYSTEM, user_text=user_prompt, bot_type="conductor"),
            temperature=0.85,
            max_rounds=8,
            response_format={"type": "json_object"},
            on_tool_call=lambda name, args: log.info("创意调研: %s(%s)", name, str(args)[:80]),
        )
        agent.add_tools([
            WEB_SEARCH_TOOL, TRENDING_TOOL, SEARCH_PLATFORM_TOOL,
            BRAND_INFO_TOOL, TEAM_DECISIONS_TOOL, PAST_CONTENT_TOOL,
        ])

        parsed, result = agent.run_json(user_prompt)
        log.info("创意生成完成: %d 轮工具调用, %d 次工具使用",
                 result.rounds_used, len(result.tool_calls_made))

        items = []
        if parsed:
            items = parsed.get("ideas", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(items, list):
            items = [items] if items else []

        ideas = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ideas.append(ContentIdea(
                title=item.get("title", ""),
                angle=item.get("angle", ""),
                hook=item.get("hook", ""),
                target_platform=item.get("target_platform", ""),
                content_type=item.get("content_type", content_type),
                estimated_appeal=float(item.get("estimated_appeal", 0)),
                reasoning=item.get("reasoning", ""),
            ))
        ideas.sort(key=lambda x: x.estimated_appeal, reverse=True)
        log.info("快速模式产出 %d 个创意", len(ideas))
        return ideas
    except Exception as e:
        log.error("创意生成失败: %s", e)
        return _generate_ideas_fallback(trends, topic, brand, content_type,
                                        target_platforms, persona, target_audience, content_goals)


def _generate_ideas_fallback(
    trends: list[TrendItem], topic: str, brand: str, content_type: str,
    target_platforms: Optional[list[str]], persona: str, target_audience: str,
    content_goals: str,
) -> list[ContentIdea]:
    """AgentLoop 失败时的回退：用简单 chat_completion + JSON mode。"""
    log.info("回退到简单模式生成创意...")
    trend_text = "\n".join(
        f"- [{t.platform}] {t.title} (热度:{t.heat})"
        for t in trends[:30]
    ) or "（暂无热点数据）"

    extra = []
    if persona:
        extra.append(f"人设：{persona}")
    if target_audience:
        extra.append(f"受众：{target_audience}")
    if content_goals:
        extra.append(f"目标：{content_goals}")

    user_prompt = (
        f"热点：\n{trend_text}\n\n主题：{topic or '从热点挖掘'}\n品牌：{brand or '无'}\n"
        f"平台：{', '.join(target_platforms or ['xiaohongshu'])}\n"
        + "\n".join(extra) + "\n\n产出5个创意，输出JSON：{\"ideas\": [...]}"
    )
    fallback_system = (
        "你是自媒体内容策划师。产出5个创意，输出JSON：{\"ideas\": [{\"title\",\"angle\",\"hook\","
        "\"target_platform\",\"content_type\",\"estimated_appeal\",\"reasoning\"}]}"
    )
    try:
        raw = chat_completion(
            provider="deepseek",
            system=enrich_prompt(fallback_system, user_text=user_prompt, bot_type="conductor"),
            user=user_prompt,
            temperature=0.85, response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        items = data.get("ideas", data) if isinstance(data, dict) else data
        return [ContentIdea(
            title=it.get("title", ""), angle=it.get("angle", ""),
            hook=it.get("hook", ""), target_platform=it.get("target_platform", ""),
            content_type=it.get("content_type", content_type),
            estimated_appeal=float(it.get("estimated_appeal", 0)),
            reasoning=it.get("reasoning", ""),
        ) for it in (items if isinstance(items, list) else [])]
    except Exception as e:
        log.error("回退创意生成也失败: %s", e)
        return []


def generate_ideas_deep(
    topic: str,
    brand: str = "",
    context: str = "",
    persona: str = "",
    target_audience: str = "",
    content_goals: str = "",
) -> tuple[list[ContentIdea], str, str]:
    """
    深度模式：调用 brainstorm 脑暴，从脑暴结果提取创意；
    后续创作阶段由 content_factory 调用 creative prompt 机器人生成给火山的需求。

    返回 (ideas, brainstorm_session_path, creative_step_note)
    """
    from brainstorm.run import run_brainstorm

    extra = []
    if persona:
        extra.append(f"发帖人设：{persona}")
    if target_audience:
        extra.append(f"目标受众：{target_audience}")
    if content_goals:
        extra.append(f"内容目标：{content_goals}")
    full_context = (context + "\n\n" + "\n".join(extra)).strip() if extra else context

    log.info("深度模式：启动脑暴...")
    conductor_webhook = (os.environ.get("CONDUCTOR_BRAINSTORM_WEBHOOK") or "").strip() or None
    bs_path = run_brainstorm(
        topic=topic,
        context=full_context,
        brand=brand,
        deliverables="自媒体内容方案（标题、切入角度、文案框架、视觉方向）",
        webhook=conductor_webhook,
    )

    bs_content = Path(bs_path).read_text(encoding="utf-8") if Path(bs_path).exists() else ""

    log.info("深度模式：从脑暴结果提取创意（火山需求由 content_factory 调用 creative prompt 生成）")
    ideas = _extract_ideas_from_brainstorm(bs_content, topic)
    log.info("深度模式产出 %d 个创意", len(ideas))
    return ideas, bs_path, "creative_prompt"


def _extract_ideas_from_brainstorm(bs_content: str, topic: str) -> list[ContentIdea]:
    """从脑暴讨论结果中提取结构化创意（供 content_factory 调用 creative prompt 生成给火山的需求）。"""
    extract_prompt = f"""从以下脑暴讨论中，提取最终保留的创意方向，转化为自媒体内容创意。

脑暴讨论（摘要）：
{bs_content[-6000:]}

输出 JSON 数组，每个元素：
{{"title": "...", "angle": "...", "hook": "前3秒钩子", "target_platform": "...", "content_type": "short_video/image_post/article", "estimated_appeal": 0.8, "reasoning": "..."}}

只输出 JSON。"""

    try:
        raw = chat_completion(provider="deepseek", system="你是内容提取专家。从脑暴讨论记录中提取可执行的内容创意。只输出JSON。", user=extract_prompt, temperature=0.3)
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        items = json.loads(json_match.group() if json_match else raw)
        return [ContentIdea(
            title=item.get("title", ""), angle=item.get("angle", ""),
            hook=item.get("hook", ""), target_platform=item.get("target_platform", ""),
            content_type=item.get("content_type", "short_video"),
            estimated_appeal=float(item.get("estimated_appeal", 0.7)),
            reasoning=item.get("reasoning", ""),
        ) for item in items]
    except Exception as e:
        log.error("从脑暴结果提取创意失败: %s", e)
        return [ContentIdea(title=topic, angle="基于脑暴讨论", hook="", estimated_appeal=0.7)]


def select_best_idea(ideas: list[ContentIdea]) -> ContentIdea:
    """选择最佳创意，用 JSON mode 保证输出格式。"""
    if len(ideas) <= 1:
        return ideas[0]

    ideas_text = "\n".join(
        f"[{i}] {idea.title} | 角度: {idea.angle} | 钩子: {idea.hook} | 吸引力: {idea.estimated_appeal}"
        for i, idea in enumerate(ideas)
    )
    try:
        raw = chat_completion(
            provider="deepseek", system=SELECTION_SYSTEM, user=ideas_text,
            temperature=0.3, response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        idx = int(data.get("selected_index", 0))
        if 0 <= idx < len(ideas):
            log.info("选择创意 #%d: %s — %s", idx, ideas[idx].title, data.get("reason", ""))
            return ideas[idx]
    except Exception:
        pass
    return ideas[0]
