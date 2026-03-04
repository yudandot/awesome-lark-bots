# -*- coding: utf-8 -*-
"""
营销技能知识库 — 提供营销方法论、策略框架等领域知识。
=====================================================

数据来源：CN-MKT-Skills/modules/*.md（内部营销知识库，22 个模块）

按 bot_type 智能筛选最相关的模块子集，并结合用户消息关键词做二次精选，
避免给 LLM 注入过多不相关内容。

用法：
  >>> from skills import load_context
  >>>
  >>> # 自动按 bot_type 筛选（通过 enrich_prompt 传入）
  >>> ctx = load_context("marketing")
  >>>
  >>> # 手动按关键词筛选
  >>> ctx = load_context("marketing", keywords=["社交媒体", "用户获取"])
  >>>
  >>> # 加载特定模块完整内容
  >>> ctx = load_context("marketing", module="19-cross-border-teamwork.md")
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from skills import Skill, register

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = _PROJECT_ROOT / "CN-MKT-Skills"
MODULES_DIR = SKILLS_DIR / "modules"

# 每个 bot 最相关的模块编号前缀（仅用于模块筛选，不用于激活判断）
_MODULE_BOT_MAP: dict[str, list[str]] = {
    "assistant":  ["02", "06", "09", "10", "11", "12", "13", "17", "19", "22"],
    "planner":    ["02", "03", "05", "06", "10", "12", "13", "14", "15", "16", "17", "18"],
    "brainstorm": ["01", "02", "03", "05", "06", "07", "08", "09", "20", "21"],
    "creative":   ["01", "04", "07", "08", "14", "18", "20", "21"],
    "conductor":  ["01", "04", "09", "10", "11", "17", "19"],
    "sentiment":  ["09"],
    "newsbot":    ["22"],
}

# Sky/TGC 特定模块 — 只在提到光遇/Sky/TGC 时才加载
_SKY_MODULES = {"01", "03", "09", "13", "22"}

# 检测用户是否在聊光遇/TGC 相关话题
_SKY_KEYWORDS = [
    "光遇", "sky", "tgc", "thatgamecompany", "陈星汉",
    "光之子", "友友会", "sky children", "sky cotl",
]

# 模块关键词索引：用户消息命中这些词时优先加载对应模块
_MODULE_KEYWORDS: dict[str, list[str]] = {
    "01": ["光遇", "sky", "品牌", "brand", "游戏设计", "game design", "陈星汉", "tgc"],
    "02": ["用户", "玩家", "受众", "audience", "lifecycle", "留存", "retention", "画像", "persona"],
    "03": ["竞品", "competitor", "原神", "genshin", "蛋仔", "swot", "定位"],
    "04": ["B站", "bilibili", "抖音", "douyin", "小红书", "微信公众号", "微博", "社媒", "平台运营"],
    "05": ["获客", "ua", "acquisition", "aso", "应用商店", "投放", "kol"],
    "06": ["数据分析", "data analytics", "指标", "kpi", "roi", "漏斗", "funnel", "营销分析"],
    "07": ["文案", "copywriting", "本地化", "localization", "翻译", "意境", "留白"],
    "08": ["素材制作", "creative asset", "视频素材", "制作规格", "production", "投放素材"],
    "09": ["社区", "community", "粉丝", "fan", "二创", "ugc", "creator"],
    "10": ["活动策划", "campaign", "营销策划", "项目管理", "timeline", "赛季活动"],
    "11": ["sop", "流程", "workflow", "日常", "routine", "审批"],
    "12": ["预算", "budget", "roi", "花费", "spending", "cost"],
    "13": ["发行", "publishing", "版号", "网易", "netease"],
    "14": ["运营", "live ops", "赛季", "season", "商业化", "monetization"],
    "15": ["测试", "beta", "上线", "launch", "soft launch"],
    "16": ["跨平台", "cross-platform", "steam", "switch", "pc", "ios", "android"],
    "17": ["代理商", "agency", "partner", "kol合作", "外包", "brief", "合作方"],
    "18": ["线下活动", "event", "周边", "merch", "ip联名", "chinajoy", "展会"],
    "19": ["跨境", "cross-border", "hq", "跨文化", "沟通", "时区", "timezone", "bridge"],
    "20": ["提案", "pitch", "presentation", "汇报", "ppt"],
    "21": ["ai营销", "chatgpt", "自动化营销", "automation", "ai工具"],
    "22": ["合规", "compliance", "版号", "regulatory", "防沉迷", "监管"],
}


class MarketingSkill(Skill):
    name = "marketing"
    description = "CN 营销知识库 — 22 个模块覆盖品牌、受众、平台、活动、预算、发行、跨境协作等"
    trigger_keywords = [
        "营销", "推广", "marketing", "获客", "增长", "用户获取",
        "campaign", "赛季活动", "预算", "budget",
        "发行", "publishing", "社区运营", "community",
        "跨境", "cross-border", "跨文化",
        "合规", "compliance", "版号",
        "竞品", "kol", "投放", "素材制作",
        "光遇", "sky", "tgc", "thatgamecompany",
    ]
    bot_types = []

    def __init__(self, modules_dir: Optional[Path] = None):
        self.modules_dir = modules_dir or MODULES_DIR

    def should_activate(self, user_text: str, bot_type: str = "", **kwargs) -> bool:
        """纯关键词激活：用户消息必须命中 trigger_keywords 或 Sky 关键词。"""
        if not self.modules_dir.exists():
            return False
        lower = user_text.lower()
        if any(kw.lower() in lower for kw in self.trigger_keywords):
            return True
        if any(kw.lower() in lower for kw in _SKY_KEYWORDS):
            return True
        return False

    def list_modules(self) -> list[dict]:
        if not self.modules_dir.exists():
            return []
        modules = []
        for f in sorted(self.modules_dir.glob("*.md")):
            num = f.stem.split("-", 1)[0] if "-" in f.stem else ""
            modules.append({
                "file": f.name,
                "key": f.stem,
                "num": num,
                "title": f.stem.split("-", 1)[-1].replace("-", " ") if "-" in f.stem else f.stem,
            })
        return modules

    def load_module(self, filename: str, header_chars: int = 1500) -> str:
        if ".." in filename or "/" in filename or "\\" in filename:
            return ""
        path = self.modules_dir / filename
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8").strip()
        return text[:header_chars] if len(text) > header_chars else text

    def load_module_full(self, filename: str) -> str:
        if ".." in filename or "/" in filename or "\\" in filename:
            return ""
        path = self.modules_dir / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _select_modules(self, bot_type: str, user_text: str, max_modules: int) -> list[dict]:
        """根据 bot_type 和 user_text 关键词智能选择最相关的模块子集。

        Sky 特定模块（01/03/09/13/22）只在用户提到光遇/Sky/TGC 时才会入选。
        """
        all_modules = self.list_modules()
        if not all_modules:
            return []

        bot_nums = set(_MODULE_BOT_MAP.get(bot_type, []))
        lower = user_text.lower() if user_text else ""

        is_sky_context = any(kw.lower() in lower for kw in _SKY_KEYWORDS) if lower else False

        keyword_matched: set[str] = set()
        if lower:
            for num, kws in _MODULE_KEYWORDS.items():
                if any(kw.lower() in lower for kw in kws):
                    keyword_matched.add(num)

        scored: list[tuple[int, dict]] = []
        for m in all_modules:
            num = m["num"]
            if num in _SKY_MODULES and not is_sky_context:
                continue
            score = 0
            if num in keyword_matched:
                score += 10
            if num in bot_nums:
                score += 5
            if score > 0:
                scored.append((score, m))

        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:max_modules]]

    def get_context(self, **kwargs) -> str:
        """
        加载营销知识上下文。支持的参数：
          bot_type: str        — 按 bot 类型筛选相关模块
          user_text: str       — 用户消息，用于关键词二次匹配
          keywords: list[str]  — 按关键词筛选（标题匹配，兼容旧接口）
          max_modules: int     — 最多加载多少个模块（默认 5）
          header_chars: int    — 每个模块截取的字符数（默认 1500）
          module: str          — 加载特定模块文件名（完整内容）
        """
        if "module" in kwargs:
            return self.load_module_full(kwargs["module"])

        max_modules = kwargs.get("max_modules", 5)
        header_chars = kwargs.get("header_chars", 1500)
        bot_type = kwargs.get("bot_type", "")
        user_text = kwargs.get("user_text", "")
        keywords = kwargs.get("keywords", [])

        if keywords:
            modules = self.list_modules()
            filtered = []
            for m in modules:
                title_lower = m["title"].lower()
                for kw in keywords:
                    if kw.lower() in title_lower or kw.lower() in m["key"].lower():
                        filtered.append(m)
                        break
            modules = filtered[:max_modules]
        elif bot_type or user_text:
            modules = self._select_modules(bot_type, user_text, max_modules)
        else:
            modules = self.list_modules()[:max_modules]

        if not modules:
            return ""

        chunks = []
        for m in modules:
            text = self.load_module(m["file"], header_chars)
            if text:
                chunks.append(f"[{m['key']}] {text}")

        if not chunks:
            return ""

        return "可参考的 CN 营销知识库：\n\n" + "\n\n---\n\n".join(chunks)


register(MarketingSkill())
