# -*- coding: utf-8 -*-
"""
品牌知识技能 — 为任何机器人提供品牌视觉风格、原则、文案调性等上下文。
=================================================================

数据来源：creative/brands/*.yaml
原来只有 creative bot 在用，现在通过 Skill 接口暴露给所有机器人。

用法：
  >>> from skills import load_context
  >>>
  >>> # 按品牌名加载
  >>> ctx = load_context("brand", brand_name="sky")
  >>>
  >>> # 从用户消息自动识别品牌
  >>> ctx = load_context("brand", detect_from="帮我做一个春日系列的素材")
  >>>
  >>> # 列出所有可用品牌
  >>> from skills.brand import BrandSkill
  >>> brands = BrandSkill().list_brands()
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from skills import Skill, register

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRANDS_DIR = _PROJECT_ROOT / "creative" / "brands"

_BRAND_KEYWORDS: dict[str, list[str]] = {
    # ⚠️ 示例：请替换为你自己的品牌关键词
    "example": [
        "示例品牌", "example brand", "mybrand",
    ],
}


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class BrandSkill(Skill):
    name = "brand"
    description = "品牌知识库 — 提供品牌视觉风格、原则、场景、角色、文案调性等"

    def __init__(self, brands_dir: Optional[Path] = None):
        self.brands_dir = brands_dir or BRANDS_DIR

    # ── 品牌发现 ──

    def list_brands(self) -> list[dict]:
        """列出所有可用品牌（不含模板）。"""
        profiles = []
        if not self.brands_dir.exists():
            return profiles
        for f in sorted(self.brands_dir.glob("*.yaml")):
            if f.name.startswith("_"):
                continue
            try:
                data = _load_yaml(f)
                profiles.append({
                    "file": f.name,
                    "key": f.stem,
                    "name": data.get("name", f.stem),
                    "category": data.get("category", ""),
                    "one_liner": data.get("one_liner", ""),
                })
            except Exception:
                continue
        return profiles

    def load_brand(self, name: str) -> Optional[dict]:
        """按品牌文件名（不含 .yaml）或品牌中文名加载。"""
        exact = self.brands_dir / f"{name}.yaml"
        if exact.exists():
            return _load_yaml(exact)
        for p in self.list_brands():
            if name.lower() in p["name"].lower():
                return _load_yaml(self.brands_dir / p["file"])
        return None

    def detect_brand(self, text: str) -> Optional[dict]:
        """根据文本中的关键词自动识别品牌并加载。"""
        lower = text.lower()
        for brand_key, keywords in _BRAND_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in lower:
                    return self.load_brand(brand_key)
        return None

    # ── 格式化为 prompt 片段 ──

    def brand_to_prompt(self, brand: dict) -> str:
        """将品牌 profile 转为可直接拼入 system prompt 的文本段落。"""
        parts = []

        name = brand.get("name", "未知品牌")
        parts.append(
            f"━━ 品牌知识：{name} ━━\n"
            f"公司：{brand.get('company', '')}\n"
            f"类别：{brand.get('category', '')}\n"
            f"简介：{brand.get('one_liner', '')}"
        )

        principles = brand.get("principles", [])
        if principles:
            lines = ["━━ 品牌原则 ━━"]
            for i, p in enumerate(principles, 1):
                line = f"{i}. {p.get('name', '')}"
                if p.get("do"):
                    line += f" — ✓ {p['do']}"
                if p.get("dont"):
                    line += f" | ✗ {p['dont']}"
                lines.append(line)
            parts.append("\n".join(lines))

        visual = brand.get("visual", {})
        if visual:
            lines = ["━━ 视觉词库 ━━"]
            for key, label in [("colors", "色彩"), ("lighting", "光影"),
                               ("textures", "质感"), ("moods", "氛围"),
                               ("camera", "运镜")]:
                items = visual.get(key, [])
                if items:
                    lines.append(f"【{label}】" + " | ".join(items))
            parts.append("\n".join(lines))

        scenes = brand.get("scenes", [])
        if scenes:
            lines = ["━━ 场景/世界观 ━━"]
            for s in scenes:
                line = f"- {s.get('name', '')}"
                if s.get("name_en"):
                    line += f" ({s['name_en']})"
                if s.get("vibe"):
                    line += f"：{s['vibe']}"
                if s.get("keywords"):
                    line += f" → {s['keywords']}"
                lines.append(line)
            parts.append("\n".join(lines))

        chars = brand.get("characters", {})
        if chars:
            lines = ["━━ 角色 ━━"]
            default_char = chars.get("default", "")
            if default_char:
                lines.append(f"默认：{default_char}")
            for v in chars.get("variants", []):
                lines.append(f"- {v.get('name', '')}：{v.get('look', '')}")
            parts.append("\n".join(lines))

        refs = brand.get("style_references", [])
        if refs:
            lines = ["━━ 视觉风格参考 ━━"]
            for r in refs:
                lines.append(f"- {r}")
            parts.append("\n".join(lines))

        neg = brand.get("negative_prompts", [])
        if neg:
            parts.append("━━ 负面提示 ━━\n" + " | ".join(neg))

        tone = brand.get("tone", {})
        if tone:
            lines = ["━━ 文案调性 ━━"]
            for tp in tone.get("principles", []):
                lines.append(f"- {tp.get('name', '')}：{tp.get('desc', '')}")
            do_list = tone.get("do", [])
            if do_list:
                lines.append(f"应该：{', '.join(do_list)}")
            dont_list = tone.get("dont", [])
            if dont_list:
                lines.append(f"避免：{', '.join(dont_list)}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    # ── Skill 接口 ──

    def get_context(self, **kwargs) -> str:
        """
        加载品牌上下文。支持的参数：
          brand_name: str  — 按名称加载
          detect_from: str — 从文本中自动识别
          raw: bool        — True 返回原始 dict 的 str，False（默认）返回 prompt 格式
        """
        brand = None
        if "brand_name" in kwargs:
            brand = self.load_brand(kwargs["brand_name"])
        elif "detect_from" in kwargs:
            brand = self.detect_brand(kwargs["detect_from"])
        if brand is None:
            return ""
        if kwargs.get("raw"):
            return str(brand)
        return self.brand_to_prompt(brand)


register(BrandSkill())
