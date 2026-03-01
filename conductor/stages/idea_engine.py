# -*- coding: utf-8 -*-
"""
Stage 2: 构思 — 脑暴或快速创意，产出内容方向。

两种模式：
  - 快速模式：直接用 LLM 产出创意方向（适合日常内容）
  - 深度模式：调用 brainstorm 五人团队脑暴 → 由 content_factory 调用 creative prompt 机器人生成给火山的需求
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from core.llm import chat_completion
from conductor.config import log
from conductor.models import TrendItem, ContentIdea


IDEATION_SYSTEM = """你是一位资深自媒体内容策划师，擅长结合热点做出有传播力的内容。

任务：根据当前热点趋势和指定主题/品牌，产出有爆款潜力的内容创意。

要求：
1. 每个创意包含：标题、切入角度、开头钩子（前3秒文案）、适合的平台、内容形式
2. 差异化——不能是人人都在做的视角，要有独特切口
3. 诚实评估每个创意的吸引力分数（0-1）
4. 钩子要具体到用户看到的第一句话/第一个画面

输出格式（严格 JSON 数组）：
[
  {
    "title": "内容标题",
    "angle": "独特切入角度（一句话）",
    "hook": "前3秒/第一行的钩子文案",
    "target_platform": "xiaohongshu/douyin/bilibili/weibo/zhihu",
    "content_type": "short_video/image_post/article",
    "estimated_appeal": 0.8,
    "reasoning": "为什么这个创意有爆款潜力"
  }
]

产出 5 个创意，按吸引力从高到低排列。只输出 JSON。"""


SELECTION_SYSTEM = """你是内容策略总监。从以下创意中选择最值得执行的一个。

评估维度：话题热度、差异化、可执行性、传播力。
返回选中创意的序号（从0开始），只返回一个数字。"""


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
    """用 LLM 快速产出内容创意。"""
    trend_text = "\n".join(
        f"- [{t.platform}] {t.title} (热度:{t.heat})"
        for t in trends[:30]
    ) or "（暂无热点数据，请根据主题自行发挥）"

    brand_context = ""
    try:
        from skills import load_context as load_skill_context
        brand_context = load_skill_context("brand", brand_name=brand) if brand else ""
    except ImportError:
        pass

    extra = []
    if persona:
        extra.append(f"发帖人设/口吻：{persona}")
    if target_audience:
        extra.append(f"目标受众：{target_audience}")
    if content_goals:
        extra.append(f"内容目标：{content_goals}")
    extra_block = "\n".join(extra) if extra else ""

    user_prompt = f"""当前热点趋势：
{trend_text}

{'主题方向：' + topic if topic else '请从热点中挖掘有潜力的内容方向'}
{'品牌：' + brand if brand else ''}
{('品牌调性：' + brand_context[:500]) if brand_context else ''}
内容形式偏好：{content_type}
目标平台：{', '.join(target_platforms or ['xiaohongshu'])}
{extra_block}

请产出 5 个有爆款潜力的内容创意。"""

    try:
        raw = chat_completion(provider="deepseek", system=IDEATION_SYSTEM, user=user_prompt, temperature=0.85)
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        items = json.loads(json_match.group() if json_match else raw)

        ideas = []
        for item in items:
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
    bs_path = run_brainstorm(
        topic=topic,
        context=full_context,
        brand=brand,
        deliverables="自媒体内容方案（标题、切入角度、文案框架、视觉方向）",
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
    """选择最佳创意（已按分数排序，可选 LLM 二次筛选）。"""
    if len(ideas) <= 1:
        return ideas[0]

    ideas_text = "\n".join(
        f"[{i}] {idea.title} | 角度: {idea.angle} | 钩子: {idea.hook} | 吸引力: {idea.estimated_appeal}"
        for i, idea in enumerate(ideas)
    )
    try:
        raw = chat_completion(provider="deepseek", system=SELECTION_SYSTEM, user=ideas_text, temperature=0.3)
        idx = int(re.search(r'\d+', raw).group())
        if 0 <= idx < len(ideas):
            return ideas[idx]
    except Exception:
        pass
    return ideas[0]
