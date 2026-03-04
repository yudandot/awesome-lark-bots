# -*- coding: utf-8 -*-
"""
CN-MKT 实战工具 Skills — 从 registry.json 自动加载 markdown skill。
====================================================================

数据来源：CN-MKT-Skills/skills/registry.json + 对应 *.md 文件

新增 skill 的方法：
  1. 在 CN-MKT-Skills/skills/ 下放一个 markdown 文件
  2. 在 CN-MKT-Skills/skills/registry.json 中加一条配置：
     {"name": "xxx", "description": "...", "file": "xxx.md",
      "trigger_keywords": [...], "sky_only": false}
  3. 重启 bot 即可生效，无需写 Python 代码
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from skills import Skill, register

log = logging.getLogger("cn_mkt_tools")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_MD_DIR = _PROJECT_ROOT / "CN-MKT-Skills" / "skills"
_REGISTRY_PATH = _SKILLS_MD_DIR / "registry.json"

_SKY_KEYWORDS = [
    "光遇", "sky", "tgc", "thatgamecompany", "陈星汉",
    "光之子", "友友会", "sky children", "sky cotl",
]


class _DynamicMdSkill(Skill):
    """从 registry.json 定义 + markdown 文件动态创建的 skill。"""

    bot_types: list[str] = []

    def __init__(self, name: str, description: str, md_path: Path,
                 trigger_keywords: list[str], sky_only: bool = False):
        self.name = name
        self.description = description
        self._path = md_path
        self.trigger_keywords = trigger_keywords
        self._sky_only = sky_only

    def should_activate(self, user_text: str, bot_type: str = "", **kwargs) -> bool:
        if not self._path.exists():
            return False
        if not self.trigger_keywords:
            return False
        lower = user_text.lower()
        kw_hit = any(kw.lower() in lower for kw in self.trigger_keywords)
        if not kw_hit:
            return False
        if self._sky_only:
            return any(kw.lower() in lower for kw in _SKY_KEYWORDS)
        return True

    def get_context(self, **kwargs) -> str:
        if not self._path.exists():
            return ""
        max_chars = kwargs.get("max_chars", 0)
        text = self._path.read_text(encoding="utf-8").strip()
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "\n\n…（内容截断，完整版请查看 CN-MKT-Skills）"
        return text


def _load_registry():
    """从 registry.json 读取配置并注册所有 skill。"""
    if not _REGISTRY_PATH.exists():
        log.debug("registry.json 不存在: %s", _REGISTRY_PATH)
        return

    try:
        entries = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("读取 registry.json 失败: %s", e)
        return

    for entry in entries:
        name = entry.get("name", "")
        md_file = entry.get("file", "")
        if not name or not md_file:
            continue

        md_path = _SKILLS_MD_DIR / md_file
        if not md_path.exists():
            log.debug("Skill md 文件不存在，跳过: %s", md_path)
            continue

        skill = _DynamicMdSkill(
            name=name,
            description=entry.get("description", ""),
            md_path=md_path,
            trigger_keywords=entry.get("trigger_keywords", []),
            sky_only=entry.get("sky_only", False),
        )
        register(skill)
        log.debug("已注册 skill: %s (%s)", name, md_file)


_load_registry()
