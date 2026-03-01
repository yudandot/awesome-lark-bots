# -*- coding: utf-8 -*-
"""
文案框架技能 — 经典营销文案模型和写作方法论。

让 content_factory / creative 在生成文案时选用合适的框架结构，
而不是凭感觉写。

数据内置（不依赖外部文件），涵盖短视频脚本、种草文案、长文等场景。
"""

from __future__ import annotations

from skills import Skill, register

_FRAMEWORKS = {
    "AIDA": {
        "full_name": "Attention → Interest → Desire → Action",
        "best_for": "通用广告文案、种草笔记",
        "structure": "开头抓注意力 → 引发兴趣 → 制造渴望 → 引导行动",
        "example": "「你还在用xxx吗？（A）发现一个方法只需3步（I）用了之后效率提升200%（D）评论区告诉你怎么get（A）」",
    },
    "PAS": {
        "full_name": "Problem → Agitate → Solution",
        "best_for": "痛点型种草、测评",
        "structure": "指出问题 → 放大痛苦 → 给出解决方案",
        "example": "「每次xxx都头疼（P）试了十几种方法都没用（A）直到发现了这个（S）」",
    },
    "FAB": {
        "full_name": "Feature → Advantage → Benefit",
        "best_for": "产品介绍、功能说明",
        "structure": "产品特点 → 优势是什么 → 对你有什么好处",
        "example": "「采用xxx技术（F）比同类快3倍（A）早上多睡10分钟（B）」",
    },
    "SCQA": {
        "full_name": "Situation → Complication → Question → Answer",
        "best_for": "深度长文、方案型内容、知乎回答",
        "structure": "背景 → 冲突/矛盾 → 核心问题 → 答案",
        "example": "「大家都在做xxx（S）但90%的人都踩了这个坑（C）到底怎么做才对？（Q）核心就三点（A）」",
    },
    "Hook-Story-Offer": {
        "full_name": "Hook → Story → Offer",
        "best_for": "短视频脚本、直播话术",
        "structure": "前3秒钩子 → 讲一个故事/案例 → 给出你的方案",
        "example": "「停！先别划走（Hook）上周我xxx结果xxx（Story）方法都在这里（Offer）」",
    },
    "4U": {
        "full_name": "Useful, Urgent, Unique, Ultra-specific",
        "best_for": "标题写作、封面文案",
        "structure": "有用+紧迫+独特+具体 四个维度打分优化标题",
        "example": "「2024年最全xxx指南（Useful+Specific） | 再不看就晚了（Urgent） | 独家整理（Unique）」",
    },
}

_FORMAT_TEMPLATES = {
    "short_video": "短视频脚本结构：Hook（前3秒）→ 正片（核心信息，节奏快）→ CTA（引导关注/评论）。推荐框架：Hook-Story-Offer、PAS",
    "image_post": "种草笔记结构：封面（信息量>美观）→ 正文（先结论后展开）→ 互动（提问/投票）。推荐框架：AIDA、PAS、FAB",
    "article": "长文结构：标题（4U 法则优化）→ 开头（SCQA 引入）→ 主体（分段+小标题）→ 总结+CTA。推荐框架：SCQA、AIDA",
}


class CopywritingSkill(Skill):
    name = "copywriting"
    description = "文案框架知识 — AIDA/PAS/FAB/SCQA 等经典模型和内容结构"
    trigger_keywords = ["文案", "标题", "脚本", "种草", "copywriting", "文章", "正文"]
    bot_types = ["conductor"]

    def should_activate(self, user_text: str, bot_type: str = "", **kwargs) -> bool:
        if bot_type in self.bot_types:
            return True
        lower = user_text.lower()
        return any(kw.lower() in lower for kw in self.trigger_keywords)

    def get_context(self, **kwargs) -> str:
        content_type = kwargs.get("content_type", "")
        framework_name = kwargs.get("framework", "")

        parts = ["[文案框架参考]"]

        if framework_name and framework_name.upper() in _FRAMEWORKS:
            fw = _FRAMEWORKS[framework_name.upper()]
            parts.append(f"\n{framework_name.upper()} ({fw['full_name']})")
            parts.append(f"适用于：{fw['best_for']}")
            parts.append(f"结构：{fw['structure']}")
            parts.append(f"示例：{fw['example']}")
            return "\n".join(parts)

        if content_type and content_type in _FORMAT_TEMPLATES:
            parts.append(f"\n{_FORMAT_TEMPLATES[content_type]}\n")

        parts.append("可选框架：")
        for name, fw in _FRAMEWORKS.items():
            parts.append(f"  {name} ({fw['full_name']})")
            parts.append(f"    适用：{fw['best_for']} | 结构：{fw['structure']}")

        return "\n".join(parts)


register(CopywritingSkill())
