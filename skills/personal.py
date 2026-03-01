# -*- coding: utf-8 -*-
"""
个人合作技能 — 让所有机器人了解你的工作风格、偏好和当前方向。

支持两种格式：
  1. Markdown (.md) — 推荐。适合有叙事深度的 profile，如 SKILL.md 格式
  2. YAML (.yaml)   — 适合结构化但简洁的 profile

Profile 放在 skills/profiles/ 下，默认加载 PERSONAL_PROFILE 环境变量指定的文件，
或目录下的第一个非模板文件（.md 优先）。

生成方式：
  1. Markdown：把 _template.yaml 的维度发给你常用的 AI，让它写成你的 collaboration skill
  2. YAML：复制 _template.yaml 并填写
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from skills import Skill, register

PROFILES_DIR = Path(__file__).parent / "profiles"


def _extract_md_name(text: str) -> str:
    """从 Markdown profile 的 frontmatter 或标题中提取名字。"""
    fm = re.search(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if fm:
        name_match = re.search(r'^name:\s*(.+)', fm.group(1), re.MULTILINE)
        if name_match:
            return name_match.group(1).strip()
    h1 = re.search(r'^#\s+(.+)', text, re.MULTILINE)
    if h1:
        return h1.group(1).strip()
    return ""


class PersonalSkill(Skill):
    name = "personal"
    description = "个人工作风格与偏好 — 让所有 bot 了解你、适应你"
    trigger_keywords = []
    bot_types = ["assistant", "creative", "brainstorm", "planner", "conductor"]

    def __init__(self, profiles_dir: Optional[Path] = None):
        self.profiles_dir = profiles_dir or PROFILES_DIR
        self._cache: Optional[str] = None
        self._cache_path: Optional[Path] = None

    def _find_profile_path(self) -> Optional[Path]:
        env_name = os.getenv("PERSONAL_PROFILE", "")
        if env_name:
            p = self.profiles_dir / env_name
            if p.exists():
                return p
            for ext in (".md", ".yaml", ".yml"):
                pe = p.with_suffix(ext)
                if pe.exists():
                    return pe

        if not self.profiles_dir.exists():
            return None

        for ext in ("*.md", "*.yaml", "*.yml"):
            for f in sorted(self.profiles_dir.glob(ext)):
                if f.name.startswith("_"):
                    continue
                return f
        return None

    def _load_md_full(self, path: Path) -> str:
        """加载完整 Markdown profile。"""
        text = path.read_text(encoding="utf-8").strip()
        fm_end = re.search(r'^---\s*\n.*?\n---\s*\n', text, re.DOTALL)
        if fm_end:
            text = text[fm_end.end():]
        return text

    def _load_md(self, path: Path, bot_type: str = "") -> str:
        """加载 Markdown profile，按 bot 类型提取最相关的段落。"""
        full = self._load_md_full(path)
        if not full:
            return ""

        sections = re.split(r'\n(?=## )', full)

        _BOT_SECTION_PRIORITY = {
            "creative": ["审美偏好", "内容偏好", "工作风格", "协作规则"],
            "brainstorm": ["工作风格", "当前关注", "协作规则"],
            "planner": ["工作风格", "协作规则"],
            "conductor": ["内容偏好", "审美偏好", "当前关注", "协作规则"],
            "assistant": ["工作风格", "协作规则"],
        }

        preamble = sections[0] if sections and not sections[0].startswith("## ") else ""
        named_sections = {s: s for s in sections if s.startswith("## ")}

        priorities = _BOT_SECTION_PRIORITY.get(bot_type, [])

        kept = []
        if preamble.strip() and bot_type not in ("planner",):
            kept.append(preamble.strip())

        for prio_kw in priorities:
            for sec in named_sections:
                if prio_kw in sec and sec not in kept:
                    kept.append(sec.strip())

        collab = [s for s in named_sections if "协作规则" in s]
        for c in collab:
            if c.strip() not in kept:
                kept.append(c.strip())

        result = "\n\n".join(kept)

        cap = 1500 if bot_type == "planner" else 3000
        if len(result) > cap:
            result = result[:cap] + "\n...(已截断)"

        return result

    def _load_yaml(self, path: Path) -> str:
        """加载 YAML profile，转换为可读文本。"""
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        if not isinstance(data, dict) or not data.get("name"):
            return ""

        parts = [f"[当前用户：{data.get('name', '未知')}]"]

        if data.get("role"):
            parts.append(f"角色：{data['role']}")
        if data.get("one_liner"):
            parts.append(f"简介：{data['one_liner']}")

        ws = data.get("work_style", {})
        if ws:
            style_bits = []
            for key in ("decision_making", "communication", "pace"):
                if ws.get(key):
                    label = {"decision_making": "决策", "communication": "沟通", "pace": "节奏"}[key]
                    style_bits.append(f"{label}：{ws[key]}")
            if style_bits:
                parts.append("工作风格：" + "；".join(style_bits))

        focus = data.get("focus_areas", [])
        if focus:
            items = []
            for f in focus:
                if isinstance(f, dict) and f.get("topic"):
                    tag = f"[{f.get('stage', '')}]" if f.get("stage") else ""
                    items.append(f"  - {f['topic']}{tag}")
            if items:
                parts.append("当前关注方向：\n" + "\n".join(items))

        cp = data.get("content_preferences", {})
        if cp:
            if cp.get("tone"):
                parts.append("内容调性偏好：" + "、".join(cp["tone"]))
            if cp.get("avoid"):
                parts.append("避免：" + "、".join(cp["avoid"]))

        rules = data.get("collaboration_rules", [])
        valid = [r for r in rules if r] if rules else []
        if valid:
            parts.append("协作规则：\n" + "\n".join(f"  - {r}" for r in valid))

        return "\n".join(parts)

    def should_activate(self, user_text: str, bot_type: str = "", **kwargs) -> bool:
        if bot_type in self.bot_types:
            return self._find_profile_path() is not None
        return False

    def get_context(self, **kwargs) -> str:
        path = self._find_profile_path()
        if not path:
            return ""

        bot_type = kwargs.get("bot_type", "")

        cache_key = f"{path}:{bot_type}"
        if self._cache and self._cache_path == cache_key:
            return self._cache

        try:
            if path.suffix == ".md":
                result = self._load_md(path, bot_type=bot_type)
            else:
                result = self._load_yaml(path)
            self._cache = result
            self._cache_path = cache_key
            return result
        except Exception:
            return ""


register(PersonalSkill())
