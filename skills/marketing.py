# -*- coding: utf-8 -*-
"""
营销技能知识库 — 提供营销方法论、策略框架等领域知识。
=====================================================

数据来源：CN-MKT-Skills/modules/*.md（内部营销知识库）
原来只有 planner bot 在 _load_skills_context() 里硬编码加载，
现在通过 Skill 接口暴露给所有机器人。

注意：CN-MKT-Skills 是内部资料，不会随代码发布到 GitHub。
如果目录不存在，技能加载会静默返回空字符串。

用法：
  >>> from skills import load_context
  >>>
  >>> # 加载全部模块摘要（默认截取前 500 字）
  >>> ctx = load_context("marketing")
  >>>
  >>> # 按关键词筛选相关模块
  >>> ctx = load_context("marketing", keywords=["社交媒体", "用户获取"])
  >>>
  >>> # 控制加载数量和截取长度
  >>> ctx = load_context("marketing", max_modules=5, header_chars=800)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from skills import Skill, register

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = _PROJECT_ROOT / "CN-MKT-Skills"
MODULES_DIR = SKILLS_DIR / "modules"


class MarketingSkill(Skill):
    name = "marketing"
    description = "营销技能知识库 — 提供营销方法论、策略框架、行业 SOP 等参考"
    trigger_keywords = ["营销", "推广", "marketing", "策略", "获客", "运营", "增长"]
    bot_types = ["planner", "conductor"]

    def __init__(self, modules_dir: Optional[Path] = None):
        self.modules_dir = modules_dir or MODULES_DIR

    def should_activate(self, user_text: str, bot_type: str = "", **kwargs) -> bool:
        if not self.modules_dir.exists():
            return False
        if bot_type in self.bot_types:
            return True
        lower = user_text.lower()
        return any(kw.lower() in lower for kw in self.trigger_keywords)

    def list_modules(self) -> list[dict]:
        """列出所有可用的知识模块。"""
        if not self.modules_dir.exists():
            return []
        modules = []
        for f in sorted(self.modules_dir.glob("*.md")):
            modules.append({
                "file": f.name,
                "key": f.stem,
                "title": f.stem.split("-", 1)[-1].replace("-", " ") if "-" in f.stem else f.stem,
            })
        return modules

    def load_module(self, filename: str, header_chars: int = 500) -> str:
        """加载单个模块的摘要（前 N 个字符）。"""
        path = self.modules_dir / filename
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8").strip()
        return text[:header_chars] if len(text) > header_chars else text

    def load_module_full(self, filename: str) -> str:
        """加载单个模块的完整内容。"""
        path = self.modules_dir / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def get_context(self, **kwargs) -> str:
        """
        加载营销知识上下文。支持的参数：
          keywords: list[str] — 按关键词筛选相关模块（标题匹配）
          max_modules: int    — 最多加载多少个模块（默认 10）
          header_chars: int   — 每个模块截取的字符数（默认 500）
          module: str         — 加载特定模块文件名（完整内容）
        """
        if "module" in kwargs:
            return self.load_module_full(kwargs["module"])

        max_modules = kwargs.get("max_modules", 10)
        header_chars = kwargs.get("header_chars", 500)
        keywords = kwargs.get("keywords", [])

        modules = self.list_modules()
        if not modules:
            return ""

        if keywords:
            filtered = []
            for m in modules:
                title_lower = m["title"].lower()
                for kw in keywords:
                    if kw.lower() in title_lower or kw.lower() in m["key"].lower():
                        filtered.append(m)
                        break
            modules = filtered

        modules = modules[:max_modules]
        if not modules:
            return ""

        chunks = []
        for m in modules:
            text = self.load_module(m["file"], header_chars)
            if text:
                chunks.append(f"[{m['key']}] {text}")

        if not chunks:
            return ""

        return "可参考的营销技能知识库：\n\n" + "\n\n---\n\n".join(chunks)


register(MarketingSkill())
