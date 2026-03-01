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

每个平台的文案要适配该平台的调性：
- 小红书：标题用 emoji + 关键词吸引点击，正文口语化、有干货感，结尾引导互动
- 抖音：开头3秒抓人，文案简短有力，多用热门话题标签
- B站：标题有信息量，正文可稍长，注重内容价值
- 微博：短平快，带话题标签，适合传播
- 知乎：专业深度，回答式结构

重要：title 和 body 必须是「可直接发到该平台的纯发布文案」。
- 禁止在 body 中写入：格式说明（如「格式二：观测记录」）、分隔线（---）、视觉/画面描述（如「（长图左：…右：…）」）、内部标注、给 AI 用的 prompt 或观测记录。正文只能是用户看到的成品文案和话题标签。
- hashtags 单独放在数组里，每条以 # 开头，不要在 body 里重复堆砌多遍。

输出 JSON：
{
  "platform_copy": {
    "平台名": {
      "title": "发布标题（一句话，可直接作标题）",
      "body": "正文（纯发布文案，无格式说明无画面描述）",
      "hashtags": ["#标签1", "#标签2", "#标签3"]
    }
  },
  "visual_description": "视觉内容的中文描述（给 creative prompt 模块用）"
}

只输出 JSON。"""


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
) -> ContentDraft:
    """根据创意生成完整内容包：文案 + 视觉 prompt。"""
    platforms = target_platforms or [idea.target_platform or "xiaohongshu"]
    draft = ContentDraft(idea=idea)

    # ── 1. 生成各平台文案 ──
    log.info("生成文案: %s → %s", idea.title, platforms)
    extra = []
    if persona:
        extra.append(f"发帖人设/口吻：{persona}")
    if target_audience:
        extra.append(f"目标受众：{target_audience}")
    if content_goals:
        extra.append(f"内容目标：{content_goals}")
    extra_block = "\n".join(extra) if extra else ""

    copy_prompt = f"""内容创意：
标题：{idea.title}
切入角度：{idea.angle}
开头钩子：{idea.hook}
内容形式：{idea.content_type}
{'品牌：' + brand if brand else ''}

目标平台：{', '.join(platforms)}
{extra_block}

请为每个平台生成适配的发布文案。"""

    try:
        raw = chat_completion(provider="deepseek", system=COPYWRITING_SYSTEM, user=copy_prompt, temperature=0.7)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(json_match.group() if json_match else raw)

        for plat, content in data.get("platform_copy", {}).items():
            title = content.get("title", "")
            body = content.get("body", "")
            tags = content.get("hashtags", [])
            full_text = f"{title}\n\n{body}\n\n{' '.join(tags)}"
            draft.platform_copy[plat] = full_text
            draft.hashtags.extend(tags)

        visual_desc = data.get("visual_description", idea.title)
        draft.text_content = visual_desc
    except Exception as e:
        log.error("文案生成失败: %s", e)
        draft.text_content = f"{idea.title}\n{idea.angle}"
        for plat in platforms:
            draft.platform_copy[plat] = f"{idea.title}\n\n{idea.angle}\n\n{idea.hook}"

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

            result = chat_completion(provider="deepseek", system=system_prompt, user=user_prompt, temperature=0.7)
            draft.visual_prompt = result

            en_match = re.search(r'Seedance prompt:\s*"([^"]+)"', result, re.IGNORECASE)
            if en_match:
                draft.visual_prompt_en = en_match.group(1)
            else:
                en_block = re.search(r'(?:Seedance|English)[^:]*[:：]\s*(.+?)(?:\n━━|\n\n|$)', result, re.DOTALL | re.IGNORECASE)
                if en_block:
                    draft.visual_prompt_en = en_block.group(1).strip().strip('"')

            log.info("视觉 Prompt 生成完成 (%d 字)", len(result))
        except Exception as e:
            log.error("creative 模块调用失败: %s", e)
            draft.visual_prompt = f"为「{idea.title}」生成视觉素材"
    else:
        draft.visual_prompt = f"为「{idea.title}」生成视觉素材（creative 模块不可用）"

    draft.hashtags = list(set(draft.hashtags))

    # ── 3. 调用火山（即梦/Seedream）生成实际图片；无素材时自动发布也会受影响，故尽量保证调用成功 ──
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
    """AI 自评内容质量。"""
    review_input = f"""内容标题：{draft.idea.title}
切入角度：{draft.idea.angle}
钩子：{draft.idea.hook}
文案示例：{list(draft.platform_copy.values())[0][:500] if draft.platform_copy else draft.text_content[:500]}
视觉方向：{draft.visual_prompt[:300]}"""

    try:
        raw = chat_completion(provider="deepseek", system=QUALITY_SYSTEM, user=review_input, temperature=0.3)
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(json_match.group() if json_match else raw)
        draft.quality_score = float(data.get("overall_score", 0.5))
        draft.quality_feedback = data.get("feedback", "")
        log.info("质量评分: %.2f — %s", draft.quality_score, draft.quality_feedback)
    except Exception as e:
        log.warning("质量评审失败: %s", e)
        draft.quality_score = 0.6

    return draft
