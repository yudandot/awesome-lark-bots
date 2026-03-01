# -*- coding: utf-8 -*-
"""
飞书消息卡片构建工具 — 所有机器人共享。
======================================

飞书 Interactive Card 由 header + elements 组成：
  header : 标题 + 颜色
  elements: markdown 段落、分隔线、备注等

本模块提供通用的卡片构建函数，让所有机器人输出一致的卡片风格。

使用示例：
  >>> from core.cards import make_card, welcome_card, progress_card, result_card
  >>>
  >>> # 基础卡片
  >>> card = make_card("标题", [{"text": "内容"}], color="blue")
  >>>
  >>> # 欢迎卡片
  >>> card = welcome_card("脑暴机器人", "我能帮你...", examples=[...], hints=[...])
  >>>
  >>> # 进度卡片
  >>> card = progress_card("正在启动脑暴", "主题：咖啡品牌 × 音乐节")
  >>>
  >>> # 结果卡片
  >>> card = result_card("脑暴完成", body="...", next_actions=["改一下", "再来一次"])

颜色可选值：blue / green / orange / red / purple / indigo / turquoise / yellow / grey
"""

from __future__ import annotations


def make_card(title: str, sections: list[dict], color: str = "blue") -> dict:
    """
    构建飞书 interactive card。

    sections 中每项可以是：
      {"text": "markdown 文本"}       → markdown 段落
      {"divider": True}               → 分隔线
      {"note": "小字提示"}            → 底部灰色提示
      {"fields": [("标签", "值"),...]} → 双列字段
    """
    elements = []
    for s in sections:
        if s.get("divider"):
            elements.append({"tag": "hr"})
        elif s.get("text"):
            elements.append({"tag": "markdown", "content": s["text"]})
        elif s.get("note"):
            elements.append({
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": s["note"]}],
            })
        elif s.get("fields"):
            fields = []
            for label, value in s["fields"]:
                fields.append({
                    "is_short": True,
                    "text": {"tag": "lark_md", "content": f"**{label}**\n{value}"},
                })
            elements.append({"tag": "div", "fields": fields})
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": color,
        },
        "elements": elements,
    }


# ── 欢迎卡片 ──

def welcome_card(
    bot_name: str,
    intro: str,
    examples: list[str] | None = None,
    hints: list[str] | None = None,
    color: str = "turquoise",
) -> dict:
    """
    统一风格的欢迎卡片。

    bot_name: 机器人名称（如"脑暴机器人"）
    intro:    一句话介绍
    examples: 使用示例列表
    hints:    底部操作提示
    """
    sections: list[dict] = [{"text": intro}]
    if examples:
        example_lines = "\n".join(f"> {e}" for e in examples)
        sections.append({"text": f"**试试这样说：**\n{example_lines}"})
    if hints:
        sections.append({"divider": True})
        sections.append({"note": "  ·  ".join(hints)})
    return make_card(f"Hi! 我是{bot_name}", sections, color=color)


# ── 进度卡片 ──

def progress_card(
    title: str,
    detail: str = "",
    color: str = "blue",
) -> dict:
    """任务已启动 / 正在处理中的卡片。"""
    sections: list[dict] = []
    if detail:
        sections.append({"text": detail})
    sections.append({"note": "处理中，完成后会通知你"})
    return make_card(f"⏳ {title}", sections, color=color)


# ── 结果卡片 ──

def result_card(
    title: str,
    body: str = "",
    fields: list[tuple[str, str]] | None = None,
    next_actions: list[str] | None = None,
    color: str = "green",
) -> dict:
    """任务完成的结果卡片。"""
    sections: list[dict] = []
    if body:
        sections.append({"text": body})
    if fields:
        sections.append({"fields": fields})
    if next_actions:
        sections.append({"divider": True})
        actions_text = "  ·  ".join(f"「{a}」" for a in next_actions)
        sections.append({"note": f"接下来你可以：{actions_text}"})
    return make_card(f"✅ {title}", sections, color=color)


# ── 错误卡片 ──

def error_card(
    title: str = "出错了",
    detail: str = "",
    suggestions: list[str] | None = None,
    color: str = "red",
) -> dict:
    """错误反馈卡片。"""
    sections: list[dict] = []
    if detail:
        sections.append({"text": detail})
    if suggestions:
        sections.append({"divider": True})
        suggestions_text = "  ·  ".join(f"「{s}」" for s in suggestions)
        sections.append({"note": f"你可以试试：{suggestions_text}"})
    return make_card(f"❌ {title}", sections, color=color)


# ── 帮助卡片 ──

def help_card(
    bot_name: str,
    sections_content: list[tuple[str, str]],
    footer: str = "",
    color: str = "blue",
) -> dict:
    """
    帮助/指令说明卡片。

    sections_content: [(小标题, 内容), ...]
    """
    sections: list[dict] = []
    for heading, content in sections_content:
        sections.append({"text": f"**{heading}**\n{content}"})
    if footer:
        sections.append({"divider": True})
        sections.append({"note": footer})
    return make_card(f"📖 {bot_name} · 使用说明", sections, color=color)


# ── 操作反馈卡片（轻量） ──

def action_card(
    title: str,
    body: str = "",
    hints: list[str] | None = None,
    color: str = "blue",
) -> dict:
    """轻量操作反馈（备忘已记、日历已建等）。"""
    sections: list[dict] = []
    if body:
        sections.append({"text": body})
    if hints:
        sections.append({"divider": True})
        sections.append({"note": "  ·  ".join(hints)})
    return make_card(title, sections, color=color)
