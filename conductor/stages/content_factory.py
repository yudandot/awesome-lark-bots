# -*- coding: utf-8 -*-
"""
Stage 3: 创作 — 调用 creative 模块生成完整内容包。

生成内容包括：
  - 各平台适配文案（标题+正文+标签）
  - 视觉素材 Prompt（中文结构化 + Seedance 英文版）
  - 实际图片素材（通过即梦 AI 生成，如果配置了 VOLC_ACCESS_KEY）
  - AI 自评质量分
"""
from __future__ import annotations

import json
import re
from typing import Optional

from core.llm import chat_completion
from core.skill_router import enrich_prompt
from conductor.config import log
from conductor.models import ContentIdea, ContentDraft

try:
    from creative.knowledge import (
        build_system_prompt, load_brand_by_name, detect_brand_from_text,
    )
    _HAS_CREATIVE = True
except ImportError:
    _HAS_CREATIVE = False


COPYWRITING_SYSTEM = """你是顶级自媒体文案专家。根据内容创意，为每个目标平台生成完整的发布文案。

你拥有工具。写文案前请务必：
1. 查 get_platform_guide — 了解目标平台的算法规则、内容规范、字数限制
2. 查 get_copywriting_framework — 选择合适的文案框架（如 AIDA、PAS、Hook-Story-Offer）
3. 查 get_team_decisions — 了解团队的内容偏好和调性要求
4. 如需灵感 → 用 search_platform 搜索相关话题的爆款文案，学习表达方式

重要：title 和 body 必须是「可直接发到该平台的纯发布文案」。
- 禁止在 body 中写入格式说明、分隔线、画面描述、内部标注
- hashtags 单独放在数组里，不在 body 里重复

最终输出 JSON：
{
  "platform_copy": {
    "平台名": {
      "title": "发布标题",
      "body": "正文（纯发布文案）",
      "hashtags": ["#标签1", "#标签2"]
    }
  },
  "visual_description": "视觉内容的中文描述"
}"""


QUALITY_SYSTEM = """你是内容质量审核专家。评估以下自媒体内容的质量。

评分维度（每项 0-1）：
1. 钩子吸引力：前3秒/第一行能否让人停下来
2. 内容价值：是否提供信息/情感/娱乐价值
3. 差异化：是否有独特视角
4. 传播力：看完是否有分享冲动
5. 品牌一致性：是否符合品牌调性（如有品牌）

输出 JSON：
{
  "overall_score": 0.75,
  "dimensions": {"hook": 0.8, "value": 0.7, "unique": 0.8, "viral": 0.7, "brand": 0.8},
  "feedback": "一句话改进建议"
}

只输出 JSON。"""


def create_content(
    idea: ContentIdea,
    brand: str = "",
    target_platforms: Optional[list[str]] = None,
    persona: str = "",
    target_audience: str = "",
    content_goals: str = "",
    revision_feedback: str = "",
) -> ContentDraft:
    """用 AgentLoop + 工具生成内容包：文案 + 视觉 prompt。LLM 可主动查平台规范、竞品、文案框架。"""
    from core.agent import AgentLoop
    from core.tools import (
        WEB_SEARCH_TOOL, SEARCH_PLATFORM_TOOL, BRAND_INFO_TOOL,
        PLATFORM_GUIDE_TOOL, COPYWRITING_FRAMEWORK_TOOL, TEAM_DECISIONS_TOOL,
    )

    platforms = target_platforms or [idea.target_platform or "xiaohongshu"]
    draft = ContentDraft(idea=idea)

    # ── 1. 用 AgentLoop 生成各平台文案 ──
    log.info("生成文案: %s → %s", idea.title, platforms)
    extra = []
    if persona:
        extra.append(f"发帖人设/口吻：{persona}")
    if target_audience:
        extra.append(f"目标受众：{target_audience}")
    if content_goals:
        extra.append(f"内容目标：{content_goals}")

    copy_prompt = (
        f"内容创意：\n标题：{idea.title}\n角度：{idea.angle}\n钩子：{idea.hook}\n"
        f"形式：{idea.content_type}\n{'品牌：' + brand if brand else ''}\n"
        f"目标平台：{', '.join(platforms)}\n"
        + ("\n".join(extra) + "\n" if extra else "")
        + "\n请先用工具调研平台规范和竞品，再为每个平台生成文案。最终输出 JSON。"
    )
    if revision_feedback:
        copy_prompt += f"\n\n上一版反馈（请针对性改进）：{revision_feedback}"

    try:
        agent = AgentLoop(
            provider="deepseek",
            system=enrich_prompt(COPYWRITING_SYSTEM, user_text=copy_prompt, bot_type="conductor"),
            temperature=0.7,
            max_rounds=6,
            response_format={"type": "json_object"},
            on_tool_call=lambda name, args: log.info("文案调研: %s(%s)", name, str(args)[:80]),
        )
        agent.add_tools([
            WEB_SEARCH_TOOL, SEARCH_PLATFORM_TOOL, BRAND_INFO_TOOL,
            PLATFORM_GUIDE_TOOL, COPYWRITING_FRAMEWORK_TOOL, TEAM_DECISIONS_TOOL,
        ])

        parsed, result = agent.run_json(copy_prompt)
        log.info("文案生成完成: %d 轮, %d 次工具调用", result.rounds_used, len(result.tool_calls_made))

        if parsed:
            for plat, content in (parsed.get("platform_copy", {})).items():
                if isinstance(content, dict):
                    title = content.get("title", "")
                    body = content.get("body", "")
                    tags = content.get("hashtags", [])
                    full_text = f"{title}\n\n{body}\n\n{' '.join(tags)}"
                    draft.platform_copy[plat] = full_text
                    draft.hashtags.extend(tags)
                elif isinstance(content, str):
                    draft.platform_copy[plat] = content

            visual_desc = parsed.get("visual_description", idea.title)
            draft.text_content = visual_desc
        else:
            raise ValueError("JSON parse failed")
    except Exception as e:
        log.warning("AgentLoop 文案生成失败(%s), 回退到简单模式", e)
        draft = _create_content_fallback(idea, brand, platforms, persona, target_audience,
                                         content_goals, revision_feedback)

    # ── 2. 生成视觉素材 Prompt（调用 creative 模块）──
    log.info("生成视觉 Prompt...")
    visual_input = f"{idea.title}，{idea.angle}。{draft.text_content}"

    if _HAS_CREATIVE:
        try:
            brand_profile = load_brand_by_name(brand) if brand else detect_brand_from_text(visual_input)
            system_prompt = build_system_prompt(brand_profile)

            target_plat = platforms[0] if platforms else "xiaohongshu"
            plat_hint = {"xiaohongshu": "小红书", "douyin": "抖音", "bilibili": "B站"}.get(target_plat, target_plat)

            user_prompt = (
                f"【用户需求】{visual_input}，{plat_hint}平台发布\n\n"
                "请生成完整的视觉素材 Prompt（中文结构化 + Seedance 英文版 + 配套文案）。"
            )

            result_text = chat_completion(provider="deepseek", system=system_prompt, user=user_prompt, temperature=0.7)
            draft.visual_prompt = result_text

            en_match = re.search(r'Seedance prompt:\s*"([^"]+)"', result_text, re.IGNORECASE)
            if en_match:
                draft.visual_prompt_en = en_match.group(1)
            else:
                en_block = re.search(r'(?:Seedance|English)[^:]*[:：]\s*(.+?)(?:\n━━|\n\n|$)', result_text, re.DOTALL | re.IGNORECASE)
                if en_block:
                    draft.visual_prompt_en = en_block.group(1).strip().strip('"')

            log.info("视觉 Prompt 生成完成 (%d 字)", len(result_text))
        except Exception as e:
            log.error("creative 模块调用失败: %s", e)
            draft.visual_prompt = f"为「{idea.title}」生成视觉素材"
    else:
        draft.visual_prompt = f"为「{idea.title}」生成视觉素材（creative 模块不可用）"

    draft.hashtags = list(set(draft.hashtags))

    # ── 3. 调用火山生成实际图片 ──
    img_prompt = _best_image_prompt_for_draft(draft)
    if img_prompt:
        try:
            from conductor.visual import generate_image
            image_urls = generate_image(prompt=img_prompt, size="1920x1920")
            if image_urls:
                draft.generated_assets = image_urls
                log.info("火山图片生成完成: %d 张", len(image_urls))
        except (ImportError, ValueError) as e:
            log.info("跳过图片生成（未配置或参数问题）: %s", e)
        except Exception as e:
            log.warning("火山图片生成失败（非致命）: %s", e)

    return draft


def _create_content_fallback(
    idea: ContentIdea, brand: str, platforms: list[str],
    persona: str, target_audience: str, content_goals: str,
    revision_feedback: str,
) -> ContentDraft:
    """AgentLoop 失败时的回退：用简单 chat_completion + JSON mode。"""
    draft = ContentDraft(idea=idea)
    extra = []
    if persona:
        extra.append(f"人设：{persona}")
    if target_audience:
        extra.append(f"受众：{target_audience}")
    if content_goals:
        extra.append(f"目标：{content_goals}")

    fallback_system = (
        "你是自媒体文案专家。为每个平台生成发布文案。输出JSON："
        '{\"platform_copy\": {\"平台\": {\"title\": \"...\", \"body\": \"...\", \"hashtags\": [\"#...\"]}},'
        ' \"visual_description\": \"...\"}'
    )
    user = (
        f"创意：{idea.title} / {idea.angle} / 钩子：{idea.hook}\n"
        f"品牌：{brand or '无'}\n平台：{', '.join(platforms)}\n"
        + "\n".join(extra)
        + (f"\n修改反馈：{revision_feedback}" if revision_feedback else "")
    )
    try:
        raw = chat_completion(
            provider="deepseek",
            system=enrich_prompt(fallback_system, user_text=user, bot_type="conductor"),
            user=user,
            temperature=0.7, response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        for plat, content in data.get("platform_copy", {}).items():
            if isinstance(content, dict):
                full_text = f"{content.get('title', '')}\n\n{content.get('body', '')}\n\n{' '.join(content.get('hashtags', []))}"
                draft.platform_copy[plat] = full_text
                draft.hashtags.extend(content.get("hashtags", []))
        draft.text_content = data.get("visual_description", idea.title)
    except Exception as e:
        log.error("回退文案生成也失败: %s", e)
        draft.text_content = f"{idea.title}\n{idea.angle}"
        for plat in platforms:
            draft.platform_copy[plat] = f"{idea.title}\n\n{idea.angle}\n\n{idea.hook}"
    return draft


def _best_image_prompt_for_draft(draft: ContentDraft) -> str:
    """从 draft 的 visual_prompt / visual_prompt_en 中选出最适合火山文生图的 prompt。"""
    return best_image_prompt_from_text(
        getattr(draft, "visual_prompt", "") or "",
        getattr(draft, "visual_prompt_en", "") or "",
    )


def best_image_prompt_from_text(visual_prompt: str, visual_prompt_en: str) -> str:
    """
    从视觉文案中选出最适合火山 Seedream 的 prompt（供创作阶段与补跑素材时共用）。
    优先：英文、长度适中；若无则从正文抽取反引号英文块或中文前段。
    """
    text = (visual_prompt or "").strip()
    en = (visual_prompt_en or "").strip()
    if len(en) >= 80 and not en.startswith("4 "):  # 避免误用 "4 竖向长图" 这类片段
        return en[:1500]
    for pattern in [
        r"`([^`]{100,})`",
        r"Prompt for Midjourney[^:]*:\s*`([^`]+)`",
        r"(?:Midjourney|DALL-E|English)[^:]*:\s*`([^`]+)`",
        r"\*\*AI绘画工具英文Prompt[^`]*`([^`]{80,})`",
    ]:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()[:1500]
    if text:
        plain = re.sub(r"^#+\s*.*$", "", text, flags=re.MULTILINE)
        plain = re.sub(r"\*\*[^*]*\*\*", "", plain)
        return plain.strip()[:500] or text[:500]
    return ""


def review_quality(draft: ContentDraft) -> ContentDraft:
    """AI 自评内容质量（使用 JSON mode 保证输出格式）。"""
    review_input = f"""内容标题：{draft.idea.title}
切入角度：{draft.idea.angle}
钩子：{draft.idea.hook}
文案示例：{list(draft.platform_copy.values())[0][:500] if draft.platform_copy else draft.text_content[:500]}
视觉方向：{draft.visual_prompt[:300]}"""

    try:
        raw = chat_completion(
            provider="deepseek", system=QUALITY_SYSTEM, user=review_input,
            temperature=0.3, response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        draft.quality_score = float(data.get("overall_score", 0.5))
        draft.quality_feedback = data.get("feedback", "")
        log.info("质量评分: %.2f — %s", draft.quality_score, draft.quality_feedback)
    except Exception as e:
        log.warning("质量评审失败: %s", e)
        draft.quality_score = 0.6

    return draft
