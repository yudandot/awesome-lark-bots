# -*- coding: utf-8 -*-
"""
skills/ — 共享技能库，让所有机器人都能调用同一套领域知识。
===========================================================

设计理念：
  每个 Skill 是一个独立的"知识包"，封装了特定领域的上下文信息。
  机器人在构建 LLM prompt 时，可以按需加载技能，把领域知识注入到对话里。

使用方式：
  >>> from skills import get_skill, list_skills, load_context
  >>>
  >>> # 查看可用技能
  >>> for s in list_skills():
  ...     print(f"{s.name}: {s.description}")
  >>>
  >>> # 加载品牌知识
  >>> brand_ctx = load_context("brand", brand_name="sky")
  >>>
  >>> # 加载营销方法论
  >>> mkt_ctx = load_context("marketing", max_modules=5)

扩展新技能：
  1. 在 skills/ 下新建 .py 文件
  2. 继承 Skill 基类，实现 get_context()
  3. 在文件末尾调用 register(YourSkill())
  4. 新技能会在 import skills 时自动注册
"""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class Skill(ABC):
    """技能基类 — 所有技能都要继承这个。"""

    name: str = ""
    description: str = ""
    trigger_keywords: list[str] = []
    bot_types: list[str] = []

    @abstractmethod
    def get_context(self, **kwargs) -> str:
        """返回可以直接拼入 LLM prompt 的上下文文本。"""
        ...

    def should_activate(self, user_text: str, bot_type: str = "", **kwargs) -> bool:
        """判断当前上下文是否应该激活此技能。子类可覆写。"""
        if self.bot_types and bot_type in self.bot_types:
            return True
        if self.trigger_keywords:
            lower = user_text.lower()
            return any(kw.lower() in lower for kw in self.trigger_keywords)
        return False

    def __repr__(self) -> str:
        return f"<Skill:{self.name}>"


# ── 全局注册表 ──

_registry: dict[str, Skill] = {}


def register(skill: Skill) -> None:
    """注册一个技能到全局注册表。"""
    _registry[skill.name] = skill


def get_skill(name: str) -> Optional[Skill]:
    """按名称获取技能，不存在返回 None。"""
    return _registry.get(name)


def list_skills() -> list[Skill]:
    """列出所有已注册的技能。"""
    return list(_registry.values())


def load_context(skill_name: str, **kwargs) -> str:
    """
    快捷方式：加载指定技能的上下文文本。
    技能不存在或加载失败时返回空字符串，不会抛异常。
    """
    skill = get_skill(skill_name)
    if skill is None:
        return ""
    try:
        return skill.get_context(**kwargs)
    except Exception:
        return ""


# ── 自动发现：import skills 时扫描本目录下所有模块并触发注册 ──

def _auto_discover() -> None:
    pkg_dir = Path(__file__).parent
    for info in pkgutil.iter_modules([str(pkg_dir)]):
        if info.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"skills.{info.name}")
        except Exception:
            pass


_auto_discover()
