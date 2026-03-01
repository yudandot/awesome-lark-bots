# -*- coding: utf-8 -*-
"""
平台运营技能 — 各社交平台的算法规则、内容规范和最佳实践。

让 content_factory / creative / planner 生成内容时自动适配平台特性，
而不是写出"放之四海皆准"的通用内容。

数据来源：skills/platform_guides/*.yaml
扩展方式：在 platform_guides/ 下新增平台 YAML 即可。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from skills import Skill, register

GUIDES_DIR = Path(__file__).parent / "platform_guides"

_PLATFORM_ALIASES = {
    "小红书": "xiaohongshu", "红书": "xiaohongshu", "xhs": "xiaohongshu",
    "抖音": "douyin", "dy": "douyin", "tiktok": "douyin",
    "B站": "bilibili", "b站": "bilibili", "哔哩哔哩": "bilibili",
    "微博": "weibo", "wb": "weibo",
    "快手": "kuaishou", "ks": "kuaishou",
    "知乎": "zhihu", "zh": "zhihu",
}


class PlatformSkill(Skill):
    name = "platform"
    description = "平台运营知识 — 各平台算法规则、内容规范、最佳实践"
    trigger_keywords = [
        "小红书", "抖音", "B站", "微博", "快手", "知乎",
        "平台", "发布", "算法", "推荐", "标签", "封面",
    ]
    bot_types = ["conductor", "planner"]

    def __init__(self, guides_dir: Optional[Path] = None):
        self.guides_dir = guides_dir or GUIDES_DIR
        self._cache: dict[str, dict] = {}

    def _detect_platforms(self, text: str) -> list[str]:
        found = set()
        lower = text.lower()
        for alias, platform_id in _PLATFORM_ALIASES.items():
            if alias.lower() in lower:
                found.add(platform_id)
        return sorted(found) if found else ["xiaohongshu"]

    def _load_guide(self, platform_id: str) -> Optional[dict]:
        if platform_id in self._cache:
            return self._cache[platform_id]

        path = self.guides_dir / f"{platform_id}.yaml"
        if not path.exists():
            return None

        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._cache[platform_id] = data
                return data
        except Exception:
            pass
        return None

    def should_activate(self, user_text: str, bot_type: str = "", **kwargs) -> bool:
        if not self.guides_dir.exists():
            return False
        if bot_type in self.bot_types:
            return True
        lower = user_text.lower()
        return any(kw.lower() in lower for kw in self.trigger_keywords)

    def get_context(self, **kwargs) -> str:
        detect_from = kwargs.get("detect_from", "")
        platforms = kwargs.get("platforms") or self._detect_platforms(detect_from)
        if isinstance(platforms, str):
            platforms = [platforms]

        chunks = []
        for pid in platforms:
            normalized = _PLATFORM_ALIASES.get(pid, pid)
            guide = self._load_guide(normalized)
            if not guide:
                continue

            lines = [f"[{guide.get('name', normalized)} 平台运营指南]"]

            algo = guide.get("algorithm", {})
            if algo:
                lines.append("推荐算法要点：")
                for k, v in algo.items():
                    if isinstance(v, list):
                        lines.append(f"  {k}: {', '.join(str(i) for i in v)}")
                    else:
                        lines.append(f"  {k}: {v}")

            specs = guide.get("content_specs", {})
            if specs:
                lines.append("内容规范：")
                for k, v in specs.items():
                    lines.append(f"  {k}: {v}")

            best = guide.get("best_practices", [])
            if best:
                lines.append("最佳实践：")
                for b in best[:8]:
                    lines.append(f"  - {b}")

            avoid = guide.get("avoid", [])
            if avoid:
                lines.append("避免：")
                for a in avoid[:5]:
                    lines.append(f"  - {a}")

            chunks.append("\n".join(lines))

        return "\n\n".join(chunks) if chunks else ""


register(PlatformSkill())
