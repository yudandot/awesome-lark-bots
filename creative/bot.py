# -*- coding: utf-8 -*-
"""
素材Bot —— 生成 AI 素材 prompt，并支持落地执行和需求管理。
=====================================================

这是什么？
  告诉这个机器人你想要什么素材（如「春日樱花的抖音预告」），
  它会生成可以直接复制到 Seedance / Nano Banana 等 AI 视频工具的 prompt。

两种使用方式：
  1. 直接生成 ：发需求描述 → 立即出 prompt
  2. 先聊后生成：发「聊聊：xxx」→ 讨论创意方向 → 发「生成」→ 出正式 prompt

输出内容：
  - 中文结构化 Prompt（画面/场景/镜头/氛围/风格）
  - Seedance 英文版（可直接复制粘贴）
  - 超 15 秒需求自动分镜 + 角色一致性建议
  - 配套平台文案

会话状态机：
  direct 模式（默认）→ 用户发需求 → 直接生成 prompt
                     → 发「聊聊：」→ 进入 chat 模式
  chat 模式（讨论中）→ 多轮对话   → 发「生成」→ 从讨论生成 prompt → 回到 direct
                     → 发「退出讨论」→ 回到 direct

运行：python3 -m creative
环境变量：CREATIVE_FEISHU_APP_ID / SECRET（或 FEISHU_APP_ID / SECRET）
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import threading
import time
import traceback
from collections import OrderedDict
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import lark_oapi as lark
from lark_oapi import EventDispatcherHandler, LogLevel

from core.feishu_client import (
    reply_message, reply_card,
    send_message_to_user, send_card_to_user,
)
from core.llm import chat_completion
from creative.knowledge import (
    list_brand_profiles, load_brand_by_name,
    build_system_prompt, build_user_prompt, build_refine_prompt,
    build_chat_system_prompt, build_generate_from_chat_prompt,
    detect_brand_from_text,
    build_exec_discuss_system_prompt, build_exec_brief_prompt,
    build_extract_brief_info_prompt,
)


_VERIFY_TOKEN = os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
_ENCRYPT_KEY = os.environ.get("FEISHU_ENCRYPT_KEY", "")

# ── 日志 ─────────────────────────────────────────────────────

_log_lock = threading.Lock()
_bot_log_path: Optional[str] = None


def _log(msg: str) -> None:
    line = f"[CreativeBot] {msg}"
    print(line, file=sys.stderr, flush=True)
    global _bot_log_path
    with _log_lock:
        if _bot_log_path is None:
            _bot_log_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "bot_creative.log"
            )
        try:
            with open(_bot_log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except Exception:
            pass


# ── 飞书消息卡片构建 ─────────────────────────────────────────

def _card(title: str, sections: list, color: str = "blue") -> dict:
    """构建飞书 interactive card。

    sections: [{"text": "markdown"}, {"divider": True}, ...]
    color: blue / green / orange / red / purple / indigo / turquoise
    """
    elements = []
    for s in sections:
        if s.get("divider"):
            elements.append({"tag": "hr"})
        elif s.get("text"):
            elements.append({
                "tag": "markdown",
                "content": s["text"],
            })
        elif s.get("note"):
            elements.append({
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": s["note"]}],
            })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": color,
        },
        "elements": elements,
    }


def _format_prompt_card(raw: str, brand_name: str) -> dict:
    """将 LLM 生成的 prompt 结果格式化为分段消息卡片。"""
    is_storyboard = bool(re.search(r"Shot\s*[12]", raw, re.IGNORECASE))

    if is_storyboard:
        return _format_storyboard_card(raw, brand_name)
    return _format_single_shot_card(raw, brand_name)


def _format_single_shot_card(raw: str, brand_name: str) -> dict:
    """单镜头模式的卡片格式。"""
    sections = []
    cn_prompt, en_prompt, copywriting = _split_prompt_sections(raw)

    if cn_prompt:
        sections.append({"text": cn_prompt.strip()})
    else:
        sections.append({"text": raw.strip()})
        return _card("素材Bot · Prompt", sections, color="blue")

    if en_prompt:
        sections.append({"divider": True})
        sections.append({"text": "**Seedance 英文版（直接复制）**\n\n" + en_prompt.strip()})

    if copywriting:
        sections.append({"divider": True})
        sections.append({"text": "**配套文案**\n\n" + copywriting.strip()})

    sections.append({"divider": True})
    sections.append({"text": "💡 满意这个方向？发「**安排制作**」生成执行Brief并提交需求"})
    sections.append({"note": f"品牌: {brand_name}  ·  「改一下：xxx」调整"})

    return _card("素材Bot · 单镜头 Prompt", sections, color="blue")


def _format_storyboard_card(raw: str, brand_name: str) -> dict:
    """分镜模式的卡片格式：按 Shot 分段展示。"""
    sections = []

    parts = _split_storyboard(raw)

    if parts["setup"]:
        sections.append({"text": parts["setup"].strip()})
        sections.append({"divider": True})

    for shot in parts["shots"]:
        sections.append({"text": shot.strip()})
        sections.append({"divider": True})

    if parts["editing"]:
        sections.append({"text": parts["editing"].strip()})
        sections.append({"divider": True})

    if parts["copywriting"]:
        sections.append({"text": "**配套文案**\n\n" + parts["copywriting"].strip()})
        sections.append({"divider": True})

    shot_count = len(parts["shots"])
    sections.append({"text": "💡 满意这个方向？发「**安排制作**」生成执行Brief并提交需求"})
    sections.append({"note": (
        f"品牌: {brand_name}  ·  共 {shot_count} 个 Shot  ·  「改一下：xxx」调整"
    )})

    return _card(f"素材Bot · {shot_count} 镜分镜 Prompt", sections, color="purple")


def _split_storyboard(raw: str) -> dict:
    """将分镜模式的 LLM 输出拆分为 setup / shots / editing / copywriting。"""
    result = {"setup": "", "shots": [], "editing": "", "copywriting": ""}

    copy_markers = ["━━ 配套文案", "**配套文案**", "### 配套文案", "## 配套文案"]
    edit_markers = ["━━ 剪辑建议", "**剪辑建议**", "### 剪辑建议", "## 剪辑建议"]

    copy_pos = -1
    for m in copy_markers:
        p = raw.find(m)
        if p != -1 and (copy_pos == -1 or p < copy_pos):
            copy_pos = p
    if copy_pos != -1:
        result["copywriting"] = raw[copy_pos:]
        for m in copy_markers:
            result["copywriting"] = result["copywriting"].replace(m, "").strip("━ \n")
        raw = raw[:copy_pos]

    edit_pos = -1
    for m in edit_markers:
        p = raw.find(m)
        if p != -1 and (edit_pos == -1 or p < edit_pos):
            edit_pos = p
    if edit_pos != -1:
        result["editing"] = raw[edit_pos:]
        raw = raw[:edit_pos]

    shot_pattern = re.compile(
        r"(━━\s*Shot\s*\d|##?\s*Shot\s*\d|\*\*Shot\s*\d)", re.IGNORECASE
    )
    shot_positions = [m.start() for m in shot_pattern.finditer(raw)]

    if shot_positions:
        result["setup"] = raw[:shot_positions[0]]
        for i, pos in enumerate(shot_positions):
            end = shot_positions[i + 1] if i + 1 < len(shot_positions) else len(raw)
            result["shots"].append(raw[pos:end])
    else:
        result["setup"] = raw

    return result


def _split_prompt_sections(raw: str) -> tuple:
    """单镜头模式：拆分为 (中文prompt, 英文prompt, 配套文案)。"""
    cn, en, copy = "", "", ""

    en_markers = [
        "━━ Seedance", "━━ **Seedance", "Seedance 英文版",
        "### Seedance", "## Seedance", "**Seedance",
        "━━ English",
    ]
    copy_markers = [
        "━━ 配套文案", "━━ **配套文案", "### 配套文案",
        "## 配套文案", "**配套文案**",
        "━━ 配套", "### 二、配套", "### 三、配套",
    ]

    en_pos = -1
    for m in en_markers:
        p = raw.find(m)
        if p != -1 and (en_pos == -1 or p < en_pos):
            en_pos = p

    copy_pos = -1
    for m in copy_markers:
        p = raw.find(m)
        if p != -1 and (copy_pos == -1 or p < copy_pos):
            copy_pos = p

    if en_pos != -1 and copy_pos != -1 and copy_pos > en_pos:
        cn = raw[:en_pos]
        en = raw[en_pos:copy_pos]
        copy = raw[copy_pos:]
    elif en_pos != -1:
        cn = raw[:en_pos]
        en = raw[en_pos:]
    elif copy_pos != -1:
        cn = raw[:copy_pos]
        copy = raw[copy_pos:]
    else:
        cn = raw

    for marker in en_markers + copy_markers:
        en = en.replace(marker, "").strip("━ \n")
        copy = copy.replace(marker, "").strip("━ \n")

    return cn.strip(), en.strip(), copy.strip()


# ── 欢迎卡片 ─────────────────────────────────────────────────

def _welcome_card() -> dict:
    profiles = list_brand_profiles()
    brand_list = "、".join(p["name"] for p in profiles) if profiles else "通用模式"

    return _card("Hi! 我是素材Bot", [
        {"text": (
            "告诉我你想要什么素材，我来帮你生成 "
            "**Seedance / Nano Banana** 等 AI 工具可直接使用的 prompt。\n"
            "概念满意后，还能一键**安排制作**，生成执行Brief并提交到素材管理表。"
        )},
        {"text": (
            "**直接出 prompt：**\n"
            "> 春日花海中一对朋友漫步的抖音预告\n"
            "> 咖啡师拉花特写，小红书15秒\n\n"
            "**想先讨论方向？**\n"
            "> 聊聊：我想做一个关于春日出游的视频\n"
            "> （聊完发「**生成**」出正式 prompt）\n\n"
            "**落地执行？**\n"
            "> prompt 生成后发「**安排制作**」→ 讨论执行细节 → 生成Brief文档 → 提交需求"
        )},
        {"divider": True},
        {"text": (
            f"当前品牌：**{brand_list}**\n"
            "不满意？发「**改一下：**更温暖一些」即可调整\n"
            "发「**帮助**」查看更多指令"
        )},
    ], color="turquoise")


# ── 会话状态 ─────────────────────────────────────────────────
# 每个用户维护一个独立的会话状态，用 LRU 策略限制最大会话数。
# 会话状态包括：当前品牌、上次生成的结果、讨论模式、对话历史等。

_MAX_SESSIONS = 200    # 最多缓存 200 个用户会话

_sessions: OrderedDict[str, dict] = OrderedDict()
_sessions_lock = threading.Lock()


def _get_session(user_key: str) -> dict:
    """获取或创建用户会话。使用 LRU 策略，超出上限时淘汰最久未访问的会话。"""
    with _sessions_lock:
        if user_key in _sessions:
            _sessions.move_to_end(user_key)
            return _sessions[user_key]
        session = {
            "brand": None,          # 当前品牌 profile（dict 或 None）
            "last_result": None,    # 上次生成的 prompt 文本（用于「改一下」）
            "brand_name": "",       # 品牌名（显示用），空=通用
            "mode": "direct",       # direct | chat | exec_discuss | exec_pending_confirm
            "chat_history": [],     # 讨论模式的对话历史
            "exec_ai_prompt": "",   # 触发执行讨论的 AI prompt
            "exec_chat_history": [],  # 执行讨论的对话历史
            "exec_doc_id": None,    # 执行Brief 文档 ID
            "exec_doc_url": None,   # 执行Brief 文档 URL
            "exec_brief_content": "",  # 生成的Brief内容（读取文档的 fallback）
        }
        _sessions[user_key] = session
        while len(_sessions) > _MAX_SESSIONS:
            _sessions.popitem(last=False)   # 淘汰最早的会话
        return session


def _update_session(user_key: str, **kwargs) -> None:
    with _sessions_lock:
        if user_key in _sessions:
            _sessions[user_key].update(kwargs)


# ── 消息解析 ─────────────────────────────────────────────────

_REFINE_PREFIXES = (
    "改一下", "改一下：", "改一下:", "修改", "修改：", "修改:",
    "调整", "调整：", "调整:", "改：", "改:",
)

_BRAND_PREFIXES = (
    "品牌", "brand", "切换品牌", "换品牌",
    "品牌：", "品牌:",
)


def _extract_text(content: str) -> str:
    if not content or not content.strip():
        return ""
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "text" in data:
            return (data["text"] or "").strip()
        return content.strip()
    except (json.JSONDecodeError, TypeError):
        return content.strip()


def _strip_leading_colon(s: str) -> str:
    return s.lstrip("：: ").strip()


_GREETING_WORDS = {
    "hi", "hello", "你好", "嗨", "hey", "halo", "哈喽", "在吗", "在不在",
    "你好呀", "hello!", "hi!", "嗨嗨", "你好！", "在？",
}


_CHAT_TRIGGERS = {
    "聊聊", "讨论", "先聊", "先讨论",
    "帮我想", "帮忙想", "帮我看看", "帮忙看看",
    "想一下", "想一想", "想想",
    "头脑风暴", "brainstorm",
    "不确定", "还没想好", "不太确定",
    "有什么建议", "给点建议", "你觉得呢", "你有什么想法",
    "什么方向", "怎么做比较好",
}

_CONFIRM_TRIGGERS = {
    "生成", "确定", "就这样", "开始生成", "出prompt", "出 prompt",
    "ok生成", "好的生成", "可以生成了", "就这个方向",
    "确认", "go", "开始", "就这样吧", "定了",
}

_EXIT_CHAT_TRIGGERS = {
    "退出讨论", "结束讨论", "不聊了", "算了",
}

_EXEC_START_TRIGGERS = {
    "安排制作", "落地执行", "提需求",
}

_EXEC_GEN_TRIGGERS = {
    "可以了", "信息够了", "差不多了", "生成brief", "生成 brief",
    "生成执行brief", "出brief", "出 brief", "生成",
}

_EXEC_SUBMIT_TRIGGERS = {
    "确认提交", "提交需求",
}

_EXEC_CANCEL_TRIGGERS = {
    "取消制作", "退出制作", "不做了", "取消",
}


def _classify_input(text: str, mode: str = "direct") -> tuple:
    """
    将用户输入分类为具体操作类型。

    根据当前模式和输入内容，判断用户意图：
      ('help',)            → 查看帮助
      ('greet',)           → 打招呼
      ('brand', arg)       → 查看/切换品牌
      ('refine', feedback) → 修改上次的 prompt
      ('generate', text)   → 直接生成 prompt（仅 direct 模式）
      ('chat_start', text) → 开始创意讨论
      ('chat_msg', text)   → 讨论中继续对话
      ('confirm',)         → 确认从讨论生成 prompt
      ('exit_chat',)       → 退出讨论模式
      ('exec_start',)      → 开始执行讨论
      ('exec_msg', text)   → 执行讨论中的消息
      ('exec_gen_brief',)  → 生成执行Brief
      ('exec_submit',)     → 确认提交需求
      ('exec_cancel',)     → 取消执行流程
    """
    t = text.strip()
    lower = t.lower().rstrip("!！~")

    if lower in ("帮助", "help", "?", "？"):
        return ("help",)

    if lower in _GREETING_WORDS:
        return ("greet",)

    # ── 执行模式（优先处理）
    if mode in ("exec_discuss", "exec_pending_confirm"):
        if lower in _EXEC_CANCEL_TRIGGERS:
            return ("exec_cancel",)
        if mode == "exec_discuss" and lower in _EXEC_GEN_TRIGGERS:
            return ("exec_gen_brief",)
        if mode == "exec_pending_confirm" and lower in _EXEC_SUBMIT_TRIGGERS:
            return ("exec_submit",)
        return ("exec_msg", t)

    # ── 安排制作入口
    if lower in _EXEC_START_TRIGGERS:
        return ("exec_start",)

    for prefix in _BRAND_PREFIXES:
        if lower == prefix.rstrip("：:"):
            return ("brand", "")
        if lower.startswith(prefix):
            arg = _strip_leading_colon(t[len(prefix):])
            return ("brand", arg)

    for prefix in _REFINE_PREFIXES:
        if lower.startswith(prefix):
            feedback = _strip_leading_colon(t[len(prefix):])
            if feedback:
                return ("refine", feedback)

    if lower in _EXIT_CHAT_TRIGGERS:
        return ("exit_chat",)

    if lower in _CONFIRM_TRIGGERS:
        return ("confirm",)

    if mode == "chat":
        return ("chat_msg", t)

    for trigger in _CHAT_TRIGGERS:
        if trigger in lower:
            return ("chat_start", t)

    if lower.endswith("?") or lower.endswith("？"):
        if any(w in lower for w in ("怎么", "什么", "你觉得", "有什么", "能不能", "可以", "建议")):
            return ("chat_start", t)

    return ("generate", t)


# ── 业务逻辑 ─────────────────────────────────────────────────

def _do_generate(user_key: str, user_input: str) -> str:
    session = _get_session(user_key)

    brand = session.get("brand")
    if not brand:
        brand = detect_brand_from_text(user_input)
        if brand:
            _update_session(user_key, brand=brand)

    system_prompt = build_system_prompt(brand, user_text=user_input)
    user_prompt = build_user_prompt(user_input)

    result = _generate_with_research(system_prompt, user_prompt, user_input)
    _update_session(user_key, last_result=result)
    return result


def _generate_with_research(system_prompt: str, user_prompt: str, raw_input: str) -> str:
    """用 AgentLoop 生成 prompt，LLM 可先搜索平台趋势再创作。"""
    try:
        from core.agent import AgentLoop
        from core.tools import (
            WEB_SEARCH_TOOL, TRENDING_TOOL, SEARCH_PLATFORM_TOOL,
            BRAND_INFO_TOOL, PLATFORM_GUIDE_TOOL,
        )

        enriched_system = system_prompt + (
            "\n\n你拥有搜索工具。在生成 prompt 之前，建议：\n"
            "1. 搜索目标平台（抖音/小红书等）上同类素材的当前流行风格和热门元素（用 search_platform）\n"
            "2. 如果用户提到了特定话题，搜一下当前热点看是否有可借力的趋势（用 get_trending）\n"
            "3. 如果需要了解平台投放规范，查平台指南（用 get_platform_guide）\n"
            "搜索结果融入 prompt 设计中，让创意更贴合真实平台生态。2-3次搜索足够，不要过度。"
        )

        agent = AgentLoop(
            provider="deepseek", system=enriched_system, max_rounds=5, temperature=0.7,
            on_tool_call=lambda name, args: _log(f"🔍 [创意调研] {name}: {str(args)[:80]}"),
        )
        from skills import collect_tools as _collect_skill_tools
        agent.add_tools([WEB_SEARCH_TOOL, TRENDING_TOOL, SEARCH_PLATFORM_TOOL,
                         BRAND_INFO_TOOL, PLATFORM_GUIDE_TOOL]
                        + _collect_skill_tools())
        result = agent.run(user_prompt)
        if result.tool_calls_made:
            _log(f"[生成] 搜索了 {len(result.tool_calls_made)} 次")
        return result.content
    except Exception as e:
        _log(f"[生成] AgentLoop 失败({e}), 回退简单调用")
        return chat_completion(
            provider="deepseek", system=system_prompt, user=user_prompt, temperature=0.7,
        )


def _do_refine(user_key: str, feedback: str) -> str:
    session = _get_session(user_key)
    last_result = session.get("last_result")

    if not last_result:
        return ""

    brand = session.get("brand")
    system_prompt = build_system_prompt(brand, user_text=feedback)
    refine_msg = build_refine_prompt(feedback)

    result = chat_completion(
        provider="deepseek",
        system=system_prompt,
        user=f"之前生成的 prompt 如下：\n\n{last_result}\n\n{refine_msg}",
        temperature=0.7,
    )
    _update_session(user_key, last_result=result)
    return result


_MAX_CHAT_HISTORY = 20


def _do_chat(user_key: str, user_input: str) -> str:
    """讨论模式：多轮对话，不输出结构化 prompt。"""
    session = _get_session(user_key)

    brand = session.get("brand")
    if not brand:
        brand = detect_brand_from_text(user_input)
        if brand:
            _update_session(user_key, brand=brand)

    history = session.get("chat_history", [])
    history.append({"role": "user", "content": user_input})
    if len(history) > _MAX_CHAT_HISTORY:
        history = history[-_MAX_CHAT_HISTORY:]

    system = build_chat_system_prompt(brand, user_text=user_input)
    messages = [{"role": "system", "content": system}] + history

    result = chat_completion(
        provider="deepseek",
        messages=messages,
        temperature=0.8,
    )

    history.append({"role": "assistant", "content": result})
    _update_session(user_key, chat_history=history, mode="chat")
    return result


def _do_generate_from_chat(user_key: str) -> str:
    """从讨论上下文中生成正式 prompt，支持搜索平台趋势。"""
    session = _get_session(user_key)
    history = session.get("chat_history", [])

    if not history:
        return ""

    chat_summary = "\n".join(
        f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}"
        for m in history
    )

    brand = session.get("brand")
    system_prompt = build_system_prompt(brand, user_text=chat_summary)
    user_prompt = build_generate_from_chat_prompt(chat_summary)

    result = _generate_with_research(system_prompt, user_prompt, chat_summary)
    _update_session(user_key, last_result=result, mode="direct", chat_history=[])
    return result


def _do_brand(user_key: str, arg: str) -> dict:
    """返回消息卡片 dict。"""
    profiles = list_brand_profiles()
    names = [f"**{p['name']}** (`{p['file'].replace('.yaml', '')}`)" for p in profiles]
    profile_list = "\n".join(f"- {n}" for n in names) if names else "- (暂无品牌 profile)"

    if not arg:
        session = _get_session(user_key)
        current = "通用模式"
        if session.get("brand"):
            current = session["brand"].get("name", "未知")
        return _card("品牌设置", [
            {"text": f"当前品牌：**{current}**"},
            {"divider": True},
            {"text": f"可用品牌：\n{profile_list}"},
            {"note": "切换品牌：发送「品牌：sky」"},
        ], color="purple")

    brand = load_brand_by_name(arg)
    if brand:
        _get_session(user_key)
        _update_session(user_key, brand=brand, last_result=None)
        name = brand.get("name", arg)
        principles = brand.get("principles", [])
        p_text = "\n".join(f"- {p.get('name', '')}" for p in principles[:5])
        return _card("品牌已切换", [
            {"text": f"当前品牌：**{name}**"},
            {"text": f"品牌原则：\n{p_text}" if p_text else ""},
            {"note": "现在发送需求即可按此品牌生成 prompt"},
        ], color="green")
    else:
        return _card("未找到品牌", [
            {"text": f"找不到品牌「{arg}」"},
            {"divider": True},
            {"text": f"可用品牌：\n{profile_list}"},
        ], color="orange")


# ── 执行落地 ─────────────────────────────────────────────────

_MAX_EXEC_CHAT_HISTORY = 20


def _start_exec_discuss(user_key: str, uid: Optional[str], mid: Optional[str], ai_prompt: str) -> None:
    """开始执行讨论流程。"""
    session = _get_session(user_key)
    brand = session.get("brand")

    _update_session(user_key,
        mode="exec_discuss",
        exec_ai_prompt=ai_prompt,
        exec_chat_history=[],
        exec_doc_id=None,
        exec_doc_url=None,
        exec_brief_content="",
    )

    system = build_exec_discuss_system_prompt(brand, ai_prompt)
    initial = "我想把这个AI创意概念落地执行。"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": initial},
    ]

    result = chat_completion(provider="deepseek", messages=messages, temperature=0.7)

    history = [
        {"role": "user", "content": initial},
        {"role": "assistant", "content": result},
    ]
    _update_session(user_key, exec_chat_history=history)

    card = _card("🎬 执行讨论", [
        {"text": result},
        {"divider": True},
        {"note": "执行讨论中  ·  继续回答  ·  发「可以了」生成执行Brief  ·  发「取消」退出"},
    ], color="green")

    if mid:
        reply_card(mid, card)
    elif uid:
        send_card_to_user(uid, card)


def _do_exec_chat(user_key: str, uid: Optional[str], mid: str, user_input: str) -> None:
    """执行讨论中的对话。"""
    session = _get_session(user_key)
    brand = session.get("brand")
    ai_prompt = session.get("exec_ai_prompt", "")

    history = list(session.get("exec_chat_history", []))
    history.append({"role": "user", "content": user_input})
    if len(history) > _MAX_EXEC_CHAT_HISTORY:
        history = history[-_MAX_EXEC_CHAT_HISTORY:]

    system = build_exec_discuss_system_prompt(brand, ai_prompt, user_text=user_input)
    messages = [{"role": "system", "content": system}] + history

    result = chat_completion(provider="deepseek", messages=messages, temperature=0.7)

    history.append({"role": "assistant", "content": result})
    _update_session(user_key, exec_chat_history=history)

    card = _card("🎬 执行讨论", [
        {"text": result},
        {"divider": True},
        {"note": "执行讨论中  ·  继续回答  ·  发「可以了」生成执行Brief  ·  发「取消」退出"},
    ], color="green")
    reply_card(mid, card)


def _do_generate_exec_brief(user_key: str, uid: Optional[str], mid: str) -> None:
    """从执行讨论生成Brief云文档。"""
    session = _get_session(user_key)
    ai_prompt = session.get("exec_ai_prompt", "")
    history = session.get("exec_chat_history", [])

    if not history:
        reply_card(mid, _card("没有讨论内容", [
            {"text": "请先进行执行讨论，再生成Brief。"},
        ], color="orange"))
        return

    reply_card(mid, _card("正在生成执行Brief…", [
        {"text": "根据讨论内容生成Brief文档中"},
        {"note": "通常需要 15-30 秒"},
    ], color="indigo"))

    discussion = "\n".join(
        f"{'用户' if m['role'] == 'user' else '助手'}: {m['content']}"
        for m in history
    )

    brief_prompt = build_exec_brief_prompt(discussion, ai_prompt)
    brief_content = chat_completion(
        provider="deepseek",
        system="你是一个专业的素材需求Brief撰写助手。请用Markdown格式输出。",
        user=brief_prompt,
        temperature=0.5,
    )

    if not brief_content:
        reply_message(mid, "生成Brief失败，请稍后重试。")
        return

    from core.feishu_client import create_document_with_content

    brand = session.get("brand")
    brand_name = brand.get("name", "") if brand else ""
    doc_title = f"素材执行Brief - {brand_name or '创意素材'}"

    ok, url_or_err = create_document_with_content(doc_title, brief_content, owner_open_id=uid)

    if ok:
        doc_url = url_or_err
        doc_id = ""
        if "/docx/" in doc_url:
            doc_id = doc_url.split("/docx/")[-1].split("?")[0].split("/")[0]

        _update_session(user_key,
            mode="exec_pending_confirm",
            exec_doc_id=doc_id,
            exec_doc_url=doc_url,
            exec_brief_content=brief_content,
        )

        card = _card("📝 执行Brief已生成", [
            {"text": f"请查看并修改Brief文档：\n\n👉 [点击打开文档]({doc_url})"},
            {"divider": True},
            {"text": "修改完毕后发「**确认提交**」录入素材管理表\n发「**取消**」退出"},
        ], color="green")
    else:
        _update_session(user_key,
            mode="exec_pending_confirm",
            exec_doc_id=None,
            exec_doc_url=None,
            exec_brief_content=brief_content,
        )

        card = _card("📝 执行Brief（文档创建失败，内容如下）", [
            {"text": brief_content[:2000]},
            {"divider": True},
            {"text": "发「**确认提交**」录入素材管理表\n发「**取消**」退出"},
        ], color="orange")

    if uid:
        send_card_to_user(uid, card)
    else:
        reply_card(mid, card)


def _do_submit_asset_request(user_key: str, uid: Optional[str], mid: str) -> None:
    """确认提交素材需求到管理表。"""
    session = _get_session(user_key)
    doc_id = session.get("exec_doc_id")
    brief_content = session.get("exec_brief_content", "")
    doc_url = session.get("exec_doc_url", "")

    reply_card(mid, _card("正在提交需求…", [
        {"text": "读取Brief并录入素材管理表"},
    ], color="indigo"))

    if doc_id:
        from core.feishu_client import read_document_content
        ok, content = read_document_content(doc_id)
        if ok and content:
            brief_content = content

    if not brief_content:
        reply_message(mid, "无法读取Brief内容，请重新生成。")
        _update_session(user_key, mode="direct")
        return

    extract_prompt = build_extract_brief_info_prompt(brief_content)
    raw_json = chat_completion(
        provider="deepseek",
        system="你是一个JSON数据提取助手。只返回JSON，不要其他文字。",
        user=extract_prompt,
        temperature=0.1,
    )

    info = {}
    try:
        json_match = re.search(r'\{.*\}', raw_json, re.DOTALL)
        if json_match:
            info = json.loads(json_match.group())
    except (json.JSONDecodeError, TypeError):
        pass

    from creative.asset_tracker import (
        submit_asset_request, sync_to_assistant, get_management_table_url,
    )

    ok, req_id_or_err = submit_asset_request(info, brief_url=doc_url, owner_open_id=uid)

    if not ok:
        _log(f"提交素材需求失败: {req_id_or_err}")
        reply_card(mid, _card("提交失败", [
            {"text": "录入管理表时出错，请稍后重试。"},
            {"text": "发「**确认提交**」重试"},
        ], color="red"))
        return

    req_id = req_id_or_err

    sync_ok, _ = sync_to_assistant(info, brief_url=doc_url)
    table_url = get_management_table_url()

    _update_session(user_key,
        mode="direct",
        exec_ai_prompt="",
        exec_chat_history=[],
        exec_doc_id=None,
        exec_doc_url=None,
        exec_brief_content="",
    )

    sections = [
        {"text": f"需求已提交！编号：**{req_id}**"},
    ]
    if table_url:
        sections.append({"text": f"📊 [查看素材需求管理表]({table_url})"})
    if doc_url:
        sections.append({"text": f"📝 [查看执行Brief]({doc_url})"})
    sections.append({"divider": True})

    notes = []
    if sync_ok:
        notes.append("已同步到助理项目表")
    notes.append("素材对接人可在管理表中更新进度")
    sections.append({"note": "  ·  ".join(notes)})

    card = _card("需求已提交", sections, color="green")

    if uid:
        send_card_to_user(uid, card)
    else:
        reply_card(mid, card)


# ── 消息处理 ─────────────────────────────────────────────────

_running: dict[str, bool] = {}
_running_lock = threading.Lock()


def _handle_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    _log("收到消息事件")
    try:
        if not data.event or not data.event.message:
            _log("事件或消息体为空，忽略")
            return
        msg = data.event.message
        message_id = msg.message_id
        user_text = _extract_text(msg.content or "{}")
        open_id = None
        if data.event.sender and data.event.sender.sender_id:
            open_id = getattr(data.event.sender.sender_id, "open_id", None)
        _log(f"message_id={message_id!r} open_id={open_id!r} 文本={user_text[:80]!r}")
        if not user_text:
            threading.Thread(
                target=lambda: reply_card(message_id, _welcome_card()),
                daemon=True,
            ).start()
            return
    except Exception as e:
        _log(f"解析消息异常: {e}\n{traceback.format_exc()}")
        return

    def _process(mid: str, text: str, uid: Optional[str]):
        user_key = uid or mid
        try:
            session = _get_session(user_key)
            current_mode = session.get("mode", "direct")
            action = _classify_input(text, mode=current_mode)
            _log(f"分类: mode={current_mode} action={action[0]} text={text[:40]!r}")

            # ── 帮助
            if action[0] == "help":
                reply_card(mid, _help_card())
                return

            # ── 打招呼
            if action[0] == "greet":
                reply_card(mid, _welcome_card())
                return

            # ── 品牌
            if action[0] == "brand":
                card = _do_brand(user_key, action[1])
                reply_card(mid, card)
                return

            # ── 退出讨论
            if action[0] == "exit_chat":
                _update_session(user_key, mode="direct", chat_history=[], brand=None)
                reply_card(mid, _card("已退出讨论", [
                    {"text": "讨论内容已清空。直接发送需求即可生成 prompt。"},
                ], color="blue"))
                return

            # ── 执行模式：取消
            if action[0] == "exec_cancel":
                _update_session(user_key, mode="direct", exec_ai_prompt="",
                    exec_chat_history=[], exec_doc_id=None, exec_doc_url=None,
                    exec_brief_content="")
                reply_card(mid, _card("已退出制作流程", [
                    {"text": "已退出执行讨论。可以继续生成AI prompt，或发「安排制作」重新开始。"},
                ], color="blue"))
                return

            # ── 开始执行讨论
            if action[0] == "exec_start":
                if not session.get("last_result"):
                    reply_card(mid, _card("没有可执行的AI prompt", [
                        {"text": "请先发送素材需求，生成一个AI prompt后再安排制作。"},
                    ], color="orange"))
                    return
                with _running_lock:
                    if _running.get(user_key):
                        reply_message(mid, "上一个请求还在处理中，请稍等...")
                        return
                    _running[user_key] = True
                try:
                    _start_exec_discuss(user_key, uid, mid, session["last_result"])
                except Exception as e:
                    _log(f"开始执行讨论异常: {e}\n{traceback.format_exc()}")
                    reply_message(mid, "启动执行讨论出错，请稍后重试")
                finally:
                    with _running_lock:
                        _running.pop(user_key, None)
                return

            # ── 执行讨论中的消息
            if action[0] == "exec_msg" and current_mode == "exec_discuss":
                with _running_lock:
                    if _running.get(user_key):
                        reply_message(mid, "上一个请求还在处理中，请稍等...")
                        return
                    _running[user_key] = True
                try:
                    _do_exec_chat(user_key, uid, mid, action[1])
                except Exception as e:
                    _log(f"执行讨论异常: {e}\n{traceback.format_exc()}")
                    reply_message(mid, "讨论出错，请稍后重试")
                finally:
                    with _running_lock:
                        _running.pop(user_key, None)
                return

            # ── 生成执行Brief
            if action[0] == "exec_gen_brief":
                with _running_lock:
                    if _running.get(user_key):
                        reply_message(mid, "上一个请求还在处理中，请稍等...")
                        return
                    _running[user_key] = True
                try:
                    _do_generate_exec_brief(user_key, uid, mid)
                except Exception as e:
                    _log(f"生成Brief异常: {e}\n{traceback.format_exc()}")
                    reply_message(mid, "生成Brief出错，请稍后重试")
                finally:
                    with _running_lock:
                        _running.pop(user_key, None)
                return

            # ── 确认提交需求
            if action[0] == "exec_submit":
                with _running_lock:
                    if _running.get(user_key):
                        reply_message(mid, "上一个请求还在处理中，请稍等...")
                        return
                    _running[user_key] = True
                try:
                    _do_submit_asset_request(user_key, uid, mid)
                except Exception as e:
                    _log(f"提交需求异常: {e}\n{traceback.format_exc()}")
                    reply_message(mid, "提交出错，请稍后重试")
                finally:
                    with _running_lock:
                        _running.pop(user_key, None)
                return

            # ── 等待确认阶段的其他消息
            if action[0] == "exec_msg" and current_mode == "exec_pending_confirm":
                doc_url = session.get("exec_doc_url", "")
                sections = []
                if doc_url:
                    sections.append({"text": f"👉 [打开Brief文档]({doc_url})"})
                sections.append({"text": "📝 Brief文档已生成，请查看并修改后发「**确认提交**」。"})
                sections.append({"note": "发「取消」退出制作流程"})
                reply_card(mid, _card("等待确认", sections, color="green"))
                return

            # ── 确认生成（从讨论中生成）
            if action[0] == "confirm":
                if current_mode != "chat" or not session.get("chat_history"):
                    reply_card(mid, _card("没有讨论内容", [
                        {"text": "当前没有进行中的讨论。直接发送你的需求即可生成 prompt。"},
                        {"note": "发送「聊聊：xxx」可以先讨论再生成"},
                    ], color="orange"))
                    return

                with _running_lock:
                    if _running.get(user_key):
                        reply_message(mid, "上一个请求还在处理中，请稍等...")
                        return
                    _running[user_key] = True

                turns = len(session.get("chat_history", []))
                reply_card(mid, _card("正在根据讨论生成 Prompt...", [
                    {"text": f"基于 {turns} 轮讨论内容生成"},
                    {"note": "DeepSeek 正在构思中，通常需要 15-60 秒"},
                ], color="indigo"))

                brand = session.get("brand")
                brand_name = brand.get("name", "通用") if brand else "通用"
                try:
                    result = _do_generate_from_chat(user_key)
                    if result:
                        card = _format_prompt_card(result, brand_name)
                        if uid:
                            send_card_to_user(uid, card)
                        else:
                            reply_card(mid, card)
                    else:
                        reply_message(mid, "生成失败，请稍后重试。")
                except Exception as e:
                    _log(f"从讨论生成异常: {e}\n{traceback.format_exc()}")
                    reply_message(mid, "生成出错，内部错误，请稍后重试")
                finally:
                    with _running_lock:
                        _running.pop(user_key, None)
                return

            # ── 修改
            if action[0] == "refine":
                with _running_lock:
                    if _running.get(user_key):
                        reply_message(mid, "上一个请求还在处理中，请稍等...")
                        return
                    _running[user_key] = True

                if not session.get("last_result"):
                    reply_card(mid, _card("还没有可修改的内容", [
                        {"text": "请先发送你的需求描述，生成一个 prompt 后才能修改。"},
                        {"note": "例：归来季云海和重逢主题的抖音预告"},
                    ], color="orange"))
                    with _running_lock:
                        _running.pop(user_key, None)
                    return

                reply_card(mid, _card("正在修改...", [
                    {"text": f"你的反馈：{action[1]}"},
                ], color="indigo"))

                try:
                    result = _do_refine(user_key, action[1])
                    brand = session.get("brand")
                    brand_name = brand.get("name", "通用") if brand else "通用"
                    if result:
                        card = _format_prompt_card(result, brand_name)
                        card["header"]["title"]["content"] = "修改后的 Prompt"
                        card["header"]["template"] = "indigo"
                        if uid:
                            send_card_to_user(uid, card)
                        else:
                            reply_card(mid, card)
                    else:
                        reply_message(mid, "修改失败，请稍后重试。")
                except Exception as e:
                    _log(f"修改异常: {e}\n{traceback.format_exc()}")
                    reply_message(mid, "修改出错，内部错误，请稍后重试")
                finally:
                    with _running_lock:
                        _running.pop(user_key, None)
                return

            # ── 进入讨论 / 讨论中继续对话
            if action[0] in ("chat_start", "chat_msg"):
                with _running_lock:
                    if _running.get(user_key):
                        _log(f"讨论被阻: user={user_key[:20]} (上一个请求处理中)")
                        reply_message(mid, "上一个请求还在处理中，请稍等...")
                        return
                    _running[user_key] = True

                is_first = action[0] == "chat_start" and current_mode != "chat"
                if is_first:
                    _update_session(user_key, mode="chat", chat_history=[])

                _log(f"开始讨论: user={user_key[:20]} first={is_first} text={text[:60]!r}")

                try:
                    result = _do_chat(user_key, action[1])
                    _log(f"讨论完成: user={user_key[:20]} len={len(result or '')}")
                    sections = [{"text": result}]
                    sections.append({"divider": True})
                    sections.append({"note": "讨论中  ·  继续聊  ·  发「生成」出正式 prompt  ·  发「退出讨论」结束"})
                    card = _card("创意讨论", sections, color="turquoise")
                    if is_first:
                        card["header"]["title"]["content"] = "进入创意讨论"
                    reply_card(mid, card)
                except Exception as e:
                    _log(f"讨论异常: {e}\n{traceback.format_exc()}")
                    reply_message(mid, "讨论出错，内部错误，请稍后重试")
                finally:
                    with _running_lock:
                        _running.pop(user_key, None)
                return

            # ── 直接生成
            with _running_lock:
                if _running.get(user_key):
                    reply_message(mid, "上一个请求还在处理中，请稍等...")
                    return
                _running[user_key] = True

            brand = session.get("brand")
            brand_name = brand.get("name", "通用") if brand else "通用"
            reply_card(mid, _card("正在生成...", [
                {"text": f"**需求：**{text[:200]}"},
                {"text": f"品牌：{brand_name}"},
                {"note": "DeepSeek 正在构思中，通常需要 15-60 秒"},
            ], color="indigo"))
            _log(f"开始生成: user={user_key[:20]} text={text[:60]!r}")

            try:
                result = _do_generate(user_key, action[1])
                if not result:
                    reply_message(mid, "生成失败，请检查 API 配置或稍后重试。")
                else:
                    card = _format_prompt_card(result, brand_name)
                    if uid:
                        send_card_to_user(uid, card)
                    else:
                        reply_card(mid, card)
                try:
                    from core.events import emit as _emit_event
                    _emit_event("creative", "prompt_generated",
                                f"Prompt 生成完成 ({brand_name})",
                                user_id=uid or "",
                                meta={"brand": brand_name, "topic": text[:100], "len": len(result or "")})
                except Exception:
                    pass
                _log(f"生成完成: user={user_key[:20]} len={len(result or '')}")
            except Exception as e:
                _log(f"生成异常: {e}\n{traceback.format_exc()}")
                reply_message(mid, "生成出错，内部错误，请稍后重试")
            finally:
                with _running_lock:
                    _running.pop(user_key, None)

        except Exception as e:
            _log(f"处理异常: {e}\n{traceback.format_exc()}")
            try:
                reply_message(mid, "处理出错，内部错误，请稍后重试")
            except Exception:
                pass

    threading.Thread(target=_process, args=(message_id, user_text, open_id), daemon=True).start()


def _help_card() -> dict:
    return _card("使用帮助", [
        {"text": (
            "**两种使用方式：**\n\n"
            "**1. 直接生成** — 发需求描述，立即出 prompt\n"
            "> 春日花海中一对朋友漫步的抖音预告\n"
            "> 咖啡师拉花特写，小红书15秒\n\n"
            "**2. 先讨论再生成** — 聊创意方向，确认后再出\n"
            "> 聊聊：想做一个关于春日出游的视频\n"
            "> 你觉得这个主题怎么拍？\n"
            "> （讨论完发「**生成**」出正式 prompt）"
        )},
        {"divider": True},
        {"text": (
            "**指令：**\n"
            "- 「**改一下：**更温暖一些」→ 基于上次结果修改\n"
            "- 「**品牌**」→ 查看/切换当前品牌\n"
            "- 「**品牌：sky**」→ 切换到指定品牌\n"
            "- 「**生成**」→ 讨论后确认生成 prompt\n"
            "- 「**安排制作**」→ 将AI概念落地为执行Brief并提交需求\n"
            "- 「**退出讨论**」→ 结束当前讨论\n"
            "- 「**帮助**」→ 本说明"
        )},
        {"divider": True},
        {"text": (
            "**输出内容：**\n"
            "- 中文结构化 Prompt（画面 / 场景 / 镜头 / 氛围 / 风格）\n"
            "- Seedance 英文版（可直接复制粘贴）\n"
            "- 超 15 秒需求自动分镜 + 角色一致性建议\n"
            "- 配套平台文案"
        )},
        {"note": "默认品牌：通用  ·  发「品牌：sky」可切换  ·  LLM: DeepSeek"},
    ], color="blue")


def _handle_bot_p2p_chat_entered(data) -> None:
    """用户首次打开与机器人的单聊 → 主动发送欢迎卡片。"""
    _log("用户打开了与机器人的单聊")
    try:
        open_id = None
        if hasattr(data, "event") and data.event:
            op = getattr(data.event, "operator", None) or getattr(data.event, "user_id", None)
            if op:
                open_id = getattr(op, "open_id", None)
            if not open_id:
                op_id = getattr(data.event, "operator_id", None)
                if op_id:
                    open_id = getattr(op_id, "open_id", None)
        if open_id:
            _log(f"发送欢迎卡片给 {open_id}")
            send_card_to_user(open_id, _welcome_card())
        else:
            _log("无法获取用户 open_id，跳过欢迎消息")
    except Exception as e:
        _log(f"发送欢迎消息异常: {e}\n{traceback.format_exc()}")


def _handle_message_read(_data) -> None:
    pass


# ── 长连接 ───────────────────────────────────────────────────

RECONNECT_INITIAL_DELAY = 5
RECONNECT_MAX_DELAY = 300
RECONNECT_MULTIPLIER = 2


def _run_client(app_id: str, app_secret: str) -> None:
    event_handler = (
        EventDispatcherHandler.builder(_VERIFY_TOKEN, _ENCRYPT_KEY)
        .register_p2_im_message_receive_v1(_handle_message)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(_handle_bot_p2p_chat_entered)
        .register_p2_im_message_message_read_v1(_handle_message_read)
        .build()
    )
    cli = lark.ws.Client(
        app_id, app_secret,
        event_handler=event_handler,
        log_level=LogLevel.DEBUG,
        domain="https://open.feishu.cn",
    )
    cli.start()


def main():
    app_id = (
        os.environ.get("CREATIVE_FEISHU_APP_ID")
        or os.environ.get("FEISHU_APP_ID")
        or ""
    ).strip()
    app_secret = (
        os.environ.get("CREATIVE_FEISHU_APP_SECRET")
        or os.environ.get("FEISHU_APP_SECRET")
        or ""
    ).strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "请设置环境变量 CREATIVE_FEISHU_APP_ID / CREATIVE_FEISHU_APP_SECRET "
            "（或复用 FEISHU_APP_ID / FEISHU_APP_SECRET）"
        )

    # TODO: 传递凭证应通过配置对象而非修改全局环境变量，同进程多机器人时会冲突
    os.environ["FEISHU_APP_ID"] = app_id
    os.environ["FEISHU_APP_SECRET"] = app_secret

    from creative.knowledge import CORE_SYSTEM_PROMPT
    _log("素材Bot启动")
    _log(f"代码验证: has_example={'<example>' in CORE_SYSTEM_PROMPT}, has_chat_triggers={'帮我想' in str(_CHAT_TRIGGERS)}")
    print("=" * 60)
    print("AIlarkteams 素材Bot（长连接模式）")
    print()
    print("使用方式：在飞书上给机器人发消息，描述想要的素材即可。")
    print("  例：春日花海中一对朋友漫步的抖音预告")
    print("  例：咖啡师拉花特写，小红书15秒")
    print()
    print("飞书开放平台配置：")
    print("  1. 先保持本程序运行")
    print("  2. 事件订阅 → 选择「长连接」")
    print("  3. 订阅「接收消息 v2.0」(im.message.receive_v1)")
    print("  4. 保存")
    print()
    print("断线后将自动重连，无需人工干预。")
    print("=" * 60)

    profiles = list_brand_profiles()
    if profiles:
        print(f"\n已加载品牌 profile: {', '.join(p['name'] for p in profiles)}")
    else:
        print("\n未找到品牌 profile，将使用通用模式")

    delay = RECONNECT_INITIAL_DELAY
    attempt = 0
    while True:
        attempt += 1
        _log(f"正在连接飞书… (第 {attempt} 次)")
        try:
            _run_client(app_id, app_secret)
            _log("飞书长连接已断开，将自动重连")
        except Exception as e:
            _log(f"连接失败: {e}\n{traceback.format_exc()}")
            if attempt == 1:
                print("\n若持续失败，请检查：", file=sys.stderr)
                print("  1. FEISHU_APP_ID / FEISHU_APP_SECRET 是否正确", file=sys.stderr)
                print("  2. 应用是否已发布并启用", file=sys.stderr)
                print("  3. 网络是否可访问 open.feishu.cn", file=sys.stderr)
        wait = min(delay, RECONNECT_MAX_DELAY)
        jitter = random.uniform(0, min(5, wait * 0.2))
        wait += jitter
        _log(f"{wait:.1f} 秒后重连…")
        time.sleep(wait)
        delay = min(delay * RECONNECT_MULTIPLIER, RECONNECT_MAX_DELAY)


if __name__ == "__main__":
    main()
