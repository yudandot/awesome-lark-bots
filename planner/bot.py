# -*- coding: utf-8 -*-
"""
规划机器人（长连接模式）：给机器人发消息即可启动理性规划。

运行：python3 -m planner
环境变量：PLANNER_FEISHU_APP_ID / PLANNER_FEISHU_APP_SECRET（或复用 FEISHU_APP_ID）

消息格式：
  直接发消息即为规划主题，例如：
    设计一个 AI agent 系统来自动化日常工作
  或带前缀 / 模式：
    规划：Q3 用户增长策略
    快速模式：下周产品发布计划
  多行消息第一行为主题，其余为背景材料。
  发送「帮助」查看使用说明。
"""
import json
import os
import random
import sys
import threading
import time
import traceback
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import lark_oapi as lark
from lark_oapi import EventDispatcherHandler, LogLevel

from core.feishu_client import (
    reply_message, reply_card, send_message_to_user, send_card_to_user,
    create_document_with_content, create_spreadsheet_from_markdown,
)
from core.cards import welcome_card, progress_card, result_card, error_card, help_card, make_card
from core.llm import chat_completion
from core.utils import truncate_for_display
from planner.run import run_planning, generate_doc, detect_mode
from planner.prompts import (
    PLANNER_SYSTEM, DOC_TYPES, DOC_MENU, DOC_CATEGORY_TYPES,
    detect_doc_category, build_doc_menu, FOLLOWUP_SYSTEM,
)
from memo.projects import register_project
from pitch.agencies import parse_agency_spec
from pitch.run import run_pitch

_VERIFY_TOKEN = os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
_ENCRYPT_KEY = os.environ.get("FEISHU_ENCRYPT_KEY", "")

# ── 日志 ─────────────────────────────────────────────────────

_log_lock = threading.Lock()
_bot_log_path: Optional[str] = None


def _log(msg: str) -> None:
    line = f"[PlannerBot] {msg}"
    print(line, file=sys.stderr, flush=True)
    global _bot_log_path
    with _log_lock:
        if _bot_log_path is None:
            _bot_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot_planner.log")
        try:
            with open(_bot_log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except Exception:
            pass


# ── 消息解析 ─────────────────────────────────────────────────

_TOPIC_PREFIXES = (
    "规划 ", "规划：", "规划:", "plan ", "plan:", "plan：",
    "计划 ", "计划：", "计划:",
)
_MODE_PREFIXES = (
    "快速模式 ", "快速模式：", "快速模式:",
    "分析模式 ", "分析模式：", "分析模式:",
    "方案模式 ", "方案模式：", "方案模式:",
    "执行模式 ", "执行模式：", "执行模式:",
)

# 比稿触发前缀：带冒号/空格的优先匹配，最后用裸词「比稿」「pitch」兜底（如「比稿618」）
_PITCH_PREFIXES = (
    "比稿：", "比稿:", "比稿 ", "pitch：", "pitch:", "pitch ",
    "比稿", "pitch",
)


def _is_pitch_request(text: str) -> bool:
    """检测是否是比稿请求。"""
    t = text.strip().lower()
    return any(t.startswith(p.lower()) for p in _PITCH_PREFIXES)

def _welcome() -> dict:
    return welcome_card(
        "规划机器人",
        "可以聊任何话题，也可以做深度规划。\n\n"
        "**直接聊** → 我像朋友一样跟你讨论\n"
        "**发「规划：话题」** → 启动理性六步法深度拆解\n"
        "**规划完成后** → 可以追问、生成文档、纳入项目管理\n"
        "🔍 涉及市场/行业/旅行/技术时自动联网搜索",
        examples=[
            "最近想转行，不知道该不该",
            "规划：Q3 用户增长策略",
            "快速模式：下周产品发布计划",
        ],
        hints=["日常问题直接发，复杂决策加「规划：」前缀", "营销比稿发「比稿：话题」", "发送「帮助」查看完整指南"],
    )


def _help() -> dict:
    return help_card("规划机器人", [
        ("日常对话", "直接发消息，我像朋友一样聊。生活、职业、兴趣、想法都行。"),
        ("深度规划",
         "消息前加「规划：」触发理性六步法：\n"
         "> 规划：要不要读个 MBA\n"
         "> 规划：Q3 用户增长策略\n"
         "多行消息：第一行 = 主题，其余行 = 背景材料"),
        ("五种模式",
         "**完整规划**（默认）六步全走\n"
         "**快速模式** 跳过现状分析和反馈，更快\n"
         "**分析模式** 仅问题定义 + 现状分析\n"
         "**方案模式** 仅生成 3 个方案\n"
         "**执行模式** 仅生成执行计划\n"
         "用法：快速模式：下周产品发布计划"),
        ("💬 追问",
         "规划完成后可以直接追问，1 小时内有效：\n"
         "> 第三个方案能展开说说吗？\n"
         "> 如果预算减半怎么调整？\n"
         "发「结束讨论」退出追问模式"),
        ("📄 文档生成",
         "规划完成后按受众选择文档类型：\n"
         "**给自己** → 行动 Checklist\n"
         "**给决策者** → 方案提案 / 决策一页纸\n"
         "**给团队** → 执行 Brief / 排期表\n"
         "**存档** → 规划摘要\n"
         "回复数字或名称即可生成"),
        ("📁 项目管理",
         "文档生成后回复「纳入项目 #标签」记录到项目管理表\n"
         "示例：纳入项目 #Q3增长"),
        ("🔍 联网搜索",
         "涉及市场、行业、旅行、技术选型时自动搜索\n"
         "搜索结果整合后作为规划背景材料\n"
         "个人决策类话题不触发搜索"),
        ("🏆 Agency 比稿（营销专属）",
         "做营销方案时，想要多个风格的方案PK？\n"
         "发「比稿：」后跟完整需求（可多行、可含预算/约束/目标）：\n"
         "> 比稿：618 大促营销方案\n"
         "> 比稿：洛阳茶馆光遇创作者雅集…（整段需求一条消息发）\n"
         "> 比稿 2组 体验派 增长派：新品上市\n"
         "默认 3 个 Agency（体验派/增长派/品牌派），可自定义\n"
         "流程：独立提案 → 交叉点评 → 裁决融合，约 3-4 分钟"),
    ], footer="对话秒回 | 规划约 2-4 分钟 | 追问 1 小时内有效")


def _extract_text(content: str) -> str:
    """从飞书消息 content 中提取纯文本。支持普通 text 与 post 富文本格式。"""
    if not content or not content.strip():
        return ""
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            return content.strip()
        if "text" in data:
            return (data["text"] or "").strip()
        # 飞书 post 格式：{"title":"","content":[[{"tag":"text","text":"段落1"},...],...]}
        if "content" in data:
            parts = []
            for row in data.get("content") or []:
                if not isinstance(row, list):
                    continue
                for node in row:
                    if isinstance(node, dict) and node.get("tag") == "text":
                        t = node.get("text") or ""
                        if isinstance(t, str) and t.strip():
                            parts.append(t.strip())
            if parts:
                return "\n\n".join(parts)
        return content.strip()
    except (json.JSONDecodeError, TypeError):
        return content.strip()


def _parse_planning_input(text: str) -> tuple[str, str, str]:
    t = (text or "").strip()
    mode = "完整规划"
    for prefix in _MODE_PREFIXES:
        if t.lower().startswith(prefix) or t.startswith(prefix):
            mode = prefix.rstrip(" ：:").strip()
            t = t[len(prefix):].strip()
            break
    for prefix in _TOPIC_PREFIXES:
        if t.lower().startswith(prefix):
            t = t[len(prefix):].strip()
            break
    if mode == "完整规划":
        mode = detect_mode(t)
    lines = t.split("\n", 1)
    topic = lines[0].strip()
    context = lines[1].strip() if len(lines) > 1 else ""
    if context.startswith("---"):
        context = context[3:].strip()
    return topic, context, mode


# ── 对话模式（非规划） ───────────────────────────────────────

_PLANNING_SIGNALS = (
    "规划", "计划", "策略", "方案", "怎么做", "怎么搞", "如何",
    "plan", "strategy", "how to", "how do",
    "帮我想想", "帮我分析", "帮我拆解",
)

_PLANNING_PREFIXES = _TOPIC_PREFIXES + _MODE_PREFIXES


def _needs_planning(text: str) -> bool:
    """判断消息是否需要走完整规划流水线。"""
    t = text.strip()
    for prefix in _PLANNING_PREFIXES:
        if t.lower().startswith(prefix) or t.startswith(prefix):
            return True
    lower = t.lower()
    if any(sig in lower for sig in _PLANNING_SIGNALS):
        return True
    if len(t) > 100:
        return True
    return False


_CHAT_SYSTEM = PLANNER_SYSTEM + """

当前是对话模式——不走六步流水线，但你仍然是一个有方案的人。

你要做的：
1. 先听清楚用户在说什么、真正纠结的是什么
2. 给出你的判断（不是"各有利弊"这种废话）
3. 如果值得，给 1-2 个具体方案或建议，附理由
4. 如果有思维盲区，直接指出

不要做的：
- 不要变成情感陪聊（"我理解你的感受"然后没了）
- 不要变成信息搬运工（百度能查到的不用你说）
- 不要没有立场

话题可以是任何事：生活、职业、关系、兴趣、side project、纠结的选择。
保持简洁。一个好回复 = 一个判断 + 一个方案 + 一个用户没想到的角度。

如果问题复杂到值得深度拆解，建议用户："这个值得认真规划一下，发「规划：你的问题」我帮你系统拆。"
"""


def _generate_short_title(topic: str) -> str:
    """用 LLM 将冗长话题凝练为文档标题（≤15字）。"""
    try:
        result = chat_completion(
            provider="deepseek",
            system="将用户输入凝练为一个文档标题。要求：≤15个中文字，不加标点，保留核心主题和关键限定词。只输出标题，不要解释。",
            user=topic,
        ).strip().strip("\"'「」《》【】")
        if result and len(result) <= 30:
            return result
    except Exception:
        pass
    return topic[:20]


def _chat_reply(text: str) -> str:
    """轻量对话：单轮 LLM 回复。"""
    try:
        from core.skill_router import enrich_prompt
        system = enrich_prompt(_CHAT_SYSTEM, user_text=text, bot_type="planner")
    except Exception:
        system = _CHAT_SYSTEM
    return chat_completion(provider="deepseek", system=system, user=text).strip()


# ── 文档交付 ─────────────────────────────────────────────────

_pending_docs: dict[str, dict] = {}
_pending_docs_lock = threading.Lock()
_DOC_SESSION_TTL = 1800  # 30 min

# ── 规划上下文（支持追问）────────────────────────────────
_planning_contexts: dict[str, dict] = {}
_planning_contexts_lock = threading.Lock()
_PLANNING_CONTEXT_TTL = 3600  # 1h

_EXIT_FOLLOWUP_COMMANDS = {"结束讨论", "新话题", "结束", "退出讨论", "exit", "done"}

# ── 项目纳入（待确认）───────────────────────────────────
_pending_project_regs: dict[str, dict] = {}
_pending_project_regs_lock = threading.Lock()
_PROJECT_REG_TTL = 1800  # 30 min

_DOC_DESCRIPTIONS = {
    # 给自己
    "checklist": "行动 Checklist — 按紧急度分层的待办清单",
    # 给决策者
    "proposal": "方案提案 — 为什么值得做 + 方案 + 预期回报",
    "decision": "决策一页纸 — 选了什么、为什么不选别的",
    # 给团队
    "brief": "执行 Brief — 给团队的落地方案 + 排期 + 风险",
    "timeline": "排期表 — 里程碑 + 时间 + 卡点",
    # 存档
    "summary": "规划摘要 — 核心结论 + 关键假设 + 下一步",
    # 旅行
    "itinerary": "行程表 — 按天排列的完整行程",
    "budget": "预算清单 — 分项预算 + 省钱建议",
    # 项目
    "spec": "项目 Spec — 范围定义 + MVP + 技术选型",
    "features": "功能优先级 — P0/P1/P2 功能拆分表",
    # 营销
    "calendar": "内容日历 — 按周排列的内容排期表",
}


_AUDIENCE_GROUPS = [
    ("📋 给自己", ["checklist"]),
    ("📊 给决策者 / 汇报", ["proposal", "decision"]),
    ("👥 给团队执行", ["brief", "timeline"]),
    ("📁 存档 / 复盘", ["summary"]),
]

_TOPIC_LABELS = {
    "travel": "✈️ 旅行专属",
    "project": "🛠 项目专属",
    "marketing": "📣 营销专属",
}


def _doc_menu_card(category: str = "general") -> dict:
    """根据话题类别生成受众分组的文档选择菜单卡片。"""
    from planner.prompts import DOC_TOPIC_EXTRAS
    extras = DOC_TOPIC_EXTRAS.get(category, [])

    lines = ["规划完成！根据你的需要选择文档：\n"]
    idx = 1
    for group_name, group_types in _AUDIENCE_GROUPS:
        lines.append(f"**{group_name}**")
        for dt in group_types:
            desc = _DOC_DESCRIPTIONS.get(dt, DOC_TYPES[dt]["name"])
            lines.append(f"  {idx}. {desc}")
            idx += 1

    if extras:
        label = _TOPIC_LABELS.get(category, "📎 专属")
        lines.append(f"\n**{label}**")
        for dt in extras:
            desc = _DOC_DESCRIPTIONS.get(dt, DOC_TYPES[dt]["name"])
            lines.append(f"  {idx}. {desc}")
            idx += 1

    lines.append("")
    lines.append("回复数字（如 `1`）或名称即可生成。回复 `全部` 生成所有。")
    lines.append("也可以直接提问，追问规划中的任何内容。")
    lines.append("发「结束讨论」退出追问模式。")
    return make_card("需要生成文档吗？", [
        {"text": "\n".join(lines)},
        {"divider": True},
        {"note": "1 小时内可追问  ·  30 分钟内可生成文档"},
    ], color="purple")


def _try_create_feishu_doc(title: str, content: str, open_id: Optional[str] = None) -> Optional[str]:
    """尝试创建飞书云文档，返回文档 URL 或 None。"""
    owner = open_id or (os.environ.get("FEISHU_DOC_OWNER_OPEN_ID") or "").strip() or None
    try:
        ok, result = create_document_with_content(title, content, owner_open_id=owner)
        if ok:
            return result
        _log(f"创建飞书文档失败: {result}")
    except Exception as e:
        _log(f"创建飞书文档异常: {e}")
    return None


def _try_create_feishu_sheet(title: str, content: str, open_id: Optional[str] = None) -> Optional[str]:
    """尝试从 Markdown 表格内容创建飞书电子表格，返回 URL 或 None。"""
    owner = open_id or (os.environ.get("FEISHU_DOC_OWNER_OPEN_ID") or "").strip() or None
    try:
        ok, result = create_spreadsheet_from_markdown(title, content, owner_open_id=owner)
        if ok:
            return result
        _log(f"创建飞书表格失败: {result}")
    except Exception as e:
        _log(f"创建飞书表格异常: {e}")
    return None


# ── 运行中追踪 ───────────────────────────────────────────────

_running_sessions: dict[str, str] = {}
_running_lock = threading.Lock()


# ── 文档选择解析与生成 ─────────────────────────────────────

def _resolve_doc_choice(text: str, user_key: str) -> Optional[list[str]]:
    """检查用户消息是否是文档选择，返回 doc_type 列表或 None。

    支持多种输入格式：
      "1"       → 单选
      "123"     → 多选（连续数字）
      "1,3"     → 多选（逗号分隔）
      "1 3"     → 多选（空格分隔）
      "1、3"    → 多选（顿号分隔）
      "全部"    → 全选
      "brief"   → 单选（关键词）
    """
    with _pending_docs_lock:
        session = _pending_docs.get(user_key)
    if not session:
        return None
    if time.time() - session["ts"] > _DOC_SESSION_TTL:
        with _pending_docs_lock:
            _pending_docs.pop(user_key, None)
        return None

    menu = session.get("doc_menu") or DOC_MENU
    t = text.strip().lower()

    # 先尝试精确匹配
    matched = menu.get(t)
    if matched is not None:
        return [matched] if isinstance(matched, str) else list(matched)

    # 尝试解析多数字选择：「123」「1,3」「1 3」「1、3」
    import re
    digits = re.findall(r"[1-9]", t)
    if digits and re.fullmatch(r"[\d,、\s]+", t):
        seen = set()
        result = []
        for d in digits:
            dt = menu.get(d)
            if dt and isinstance(dt, str) and dt not in seen:
                seen.add(dt)
                result.append(dt)
        if result:
            return result

    # 关键词模糊匹配
    for key, val in menu.items():
        if key in t:
            return [val] if isinstance(val, str) else list(val)

    return None


def _send_card(uid: Optional[str], mid: str, card: dict) -> None:
    if uid:
        send_card_to_user(uid, card)
    else:
        reply_card(mid, card)


def _send_msg(uid: Optional[str], mid: str, text: str) -> None:
    if uid:
        send_message_to_user(uid, text)
    else:
        reply_message(mid, text)


def _handle_doc_choice(mid: str, uid: Optional[str], user_key: str, doc_types: list[str]) -> None:
    """生成用户选择的文档并发送。

    doc 格式 → 飞书云文档（多个合并为一份），
    sheet 格式 → 飞书电子表格（各自独立），
    sheet 创建失败自动降级为文档。
    """
    with _pending_docs_lock:
        session = _pending_docs.get(user_key)
    if not session:
        reply_message(mid, "文档会话已过期，请重新发起规划。")
        return

    topic = session["topic"]
    short_title = session.get("short_title") or topic[:20]
    outputs = session["outputs"]
    open_id = session.get("open_id")
    names = [DOC_TYPES[dt]["name"] for dt in doc_types if dt in DOC_TYPES]
    reply_card(mid, progress_card("正在生成文档", f"**类型：**{' + '.join(names)}\n\n稍等片刻…"))

    doc_items: list[tuple[str, str, str]] = []    # (doc_type, doc_name, content)
    sheet_items: list[tuple[str, str, str]] = []  # (doc_type, doc_name, content)

    for doc_type in doc_types:
        cfg = DOC_TYPES.get(doc_type)
        if not cfg:
            continue
        doc_name = cfg["name"]
        _log(f"生成文档: type={doc_type} topic={topic[:40]}")
        try:
            content, fmt = generate_doc(doc_type, topic, outputs)
            if fmt == "sheet":
                sheet_items.append((doc_type, doc_name, content))
            else:
                doc_items.append((doc_type, doc_name, content))
        except Exception as e:
            _log(f"文档生成异常: {e}\n{traceback.format_exc()}")
            _send_msg(uid, mid, f"生成{doc_name}时出错了，请重试。")

    if not doc_items and not sheet_items:
        return

    all_links: list[tuple[str, str, str]] = []  # (name, url, type_label)

    # ── doc 格式：单个直接创建，多个合并 ──
    if len(doc_items) == 1:
        _, doc_name, content = doc_items[0]
        _send_card(uid, mid, result_card(doc_name, body=truncate_for_display(content), color="purple"))
        url = _try_create_feishu_doc(f"{short_title} — {doc_name}", content, open_id=open_id)
        if url:
            all_links.append((doc_name, url, "文档"))
            _log(f"飞书文档: {url}")
    elif len(doc_items) > 1:
        toc_items = [f"{i}. {name}" for i, (_, name, _) in enumerate(doc_items, 1)]
        toc = "**目录：**" + " ｜ ".join(toc_items)
        merged_parts = [f"# {short_title}\n\n{toc}\n"]
        for _, doc_name, content in doc_items:
            merged_parts.append(f"\n---\n\n## {doc_name}\n\n{content}\n")
        merged_content = "\n".join(merged_parts)
        names_str = " + ".join(name for _, name, _ in doc_items)
        _send_card(uid, mid, result_card(f"文档包（{names_str}）", body=truncate_for_display(merged_content), color="purple"))
        url = _try_create_feishu_doc(f"{short_title} — 规划文档包", merged_content, open_id=open_id)
        if url:
            all_links.append(("文档包", url, "文档"))
            _log(f"飞书合并文档: {url}")

    # ── sheet 格式：各自独立创建，失败降级为文档 ──
    for _, doc_name, content in sheet_items:
        _send_card(uid, mid, result_card(doc_name, body=truncate_for_display(content), color="purple"))
        url = _try_create_feishu_sheet(f"{short_title} — {doc_name}", content, open_id=open_id)
        if url:
            all_links.append((doc_name, url, "表格"))
            _log(f"飞书表格: {url}")
        else:
            _log(f"表格创建失败，降级为文档: {doc_name}")
            url = _try_create_feishu_doc(f"{short_title} — {doc_name}", content, open_id=open_id)
            if url:
                all_links.append((doc_name, url, "文档"))
                _log(f"飞书文档(降级): {url}")

    # ── 发送链接 ──
    if all_links:
        if len(all_links) == 1:
            name, url, type_label = all_links[0]
            _send_msg(uid, mid, f"飞书{type_label}已创建：{url}")
        else:
            parts = [f"• {name}（{tl}）：{url}" for name, url, tl in all_links]
            _send_msg(uid, mid, "飞书文件已创建：\n" + "\n".join(parts))

    # ── 剩余文档提示 ──
    category = session.get("category", "general")
    category_types = DOC_CATEGORY_TYPES.get(category, DOC_CATEGORY_TYPES["general"])
    remaining = [DOC_TYPES[k]["name"] for k in category_types if k not in doc_types and k in DOC_TYPES]
    if remaining:
        _send_msg(uid, mid, f"还可以生成：{'、'.join(remaining)}（回复对应数字或名称）")

    # ── 项目纳入提示 ──
    if all_links:
        first_name, first_url, _ = all_links[0]
        with _pending_project_regs_lock:
            _pending_project_regs[user_key] = {
                "default_name": short_title,
                "url": first_url,
                "doc_name": first_name,
                "all_links": [(n, u, t) for n, u, t in all_links],
                "spreadsheet_token": "",
                "sheet_id": "",
                "tags": [topic[:20]],
                "ts": time.time(),
            }
        _send_msg(
            uid, mid,
            "回复「纳入项目 #标签」可将此文档记录到项目管理表\n"
            "示例：纳入项目 #Q3增长  |  纳入项目 自定义名称 #标签1 #标签2\n"
            "直接回复「纳入项目」则使用默认名称和标签",
        )


# ── 规划追问 ─────────────────────────────────────────────

def _has_planning_context(user_key: str) -> Optional[dict]:
    """检查用户是否有未过期的规划上下文。"""
    with _planning_contexts_lock:
        ctx = _planning_contexts.get(user_key)
    if not ctx:
        return None
    if time.time() - ctx["ts"] > _PLANNING_CONTEXT_TTL:
        with _planning_contexts_lock:
            _planning_contexts.pop(user_key, None)
        return None
    return ctx


def _clear_planning_context(user_key: str) -> None:
    with _planning_contexts_lock:
        _planning_contexts.pop(user_key, None)


def _is_explicit_new_planning(text: str) -> bool:
    """判断是否是显式的新规划请求（带前缀），包括比稿。"""
    t = text.strip()
    for prefix in _PLANNING_PREFIXES:
        if t.lower().startswith(prefix) or t.startswith(prefix):
            return True
    if _is_pitch_request(t):
        return True
    return False


def _planning_followup(text: str, user_key: str) -> str:
    """基于规划上下文的追问回复（支持多轮对话历史）。"""
    with _planning_contexts_lock:
        ctx = _planning_contexts.get(user_key)
    if not ctx:
        return "规划上下文已过期，请重新发起规划。"

    planning_summary = "\n\n".join(
        f"第 {num} 步 {name}：\n{out}"
        for num, name, out in ctx["outputs"]
    )
    system = FOLLOWUP_SYSTEM + f"\n\n--- 你之前完成的规划 ---\n主题：{ctx['topic']}\n\n{planning_summary}"

    try:
        from core.skill_router import enrich_prompt
        system = enrich_prompt(system, user_text=text, bot_type="planner")
    except Exception:
        pass

    messages = [{"role": "system", "content": system}]
    for h in ctx.get("history", [])[-6:]:
        messages.append(h)
    messages.append({"role": "user", "content": text})

    reply = chat_completion(provider="deepseek", messages=messages).strip()

    with _planning_contexts_lock:
        ctx = _planning_contexts.get(user_key)
        if ctx:
            ctx.setdefault("history", []).append({"role": "user", "content": text})
            ctx["history"].append({"role": "assistant", "content": reply})
            if len(ctx["history"]) > 12:
                ctx["history"] = ctx["history"][-8:]
            ctx["ts"] = time.time()

    return reply


# ── 项目纳入 ─────────────────────────────────────────────

_PROJECT_REG_SIGNALS = ("纳入项目", "纳入管理", "记录项目", "add project", "register project")


def _resolve_project_registration(text: str, user_key: str) -> Optional[dict]:
    """检查用户消息是否是项目纳入请求，解析项目名和 #标签。

    支持格式：
      "纳入项目"                    → 默认名称 + 默认标签
      "纳入项目 #Q3增长"            → 默认名称 + ["Q3增长"]
      "纳入项目 我的项目 #Q3 #营销"  → 名称"我的项目" + ["Q3", "营销"]
    """
    import re

    with _pending_project_regs_lock:
        pending = _pending_project_regs.get(user_key)
    if not pending:
        return None
    if time.time() - pending["ts"] > _PROJECT_REG_TTL:
        with _pending_project_regs_lock:
            _pending_project_regs.pop(user_key, None)
        return None

    t = text.strip().lower()
    for sig in _PROJECT_REG_SIGNALS:
        if sig in t:
            remainder = text.strip()
            for sig2 in _PROJECT_REG_SIGNALS:
                remainder = remainder.replace(sig2, "").strip()

            tags = re.findall(r"#(\S+)", remainder)
            name = re.sub(r"#\S+", "", remainder).strip()

            if not name:
                name = pending.get("default_name", "")
            merged_tags = list(dict.fromkeys(
                (tags if tags else []) + pending.get("tags", [])
            ))
            return {**pending, "project_name": name, "tags": merged_tags}
    return None


def _handle_project_registration(mid: str, uid: Optional[str], user_key: str, reg_info: dict) -> None:
    """将文档纳入项目管理。"""
    project_name = reg_info.get("project_name") or reg_info.get("default_name", "未命名项目")
    url = reg_info.get("url", "")
    doc_name = reg_info.get("doc_name", "")

    try:
        project_id = register_project(
            name=project_name,
            spreadsheet_token=reg_info.get("spreadsheet_token", ""),
            sheet_id=reg_info.get("sheet_id", ""),
            url=url,
            created_by=uid or "",
            tags=reg_info.get("tags", []),
            source="planner",
            doc_type=doc_name,
        )
        _send_msg(uid, mid, f"已纳入项目管理 ✓\n项目：{project_name}\n文档：{doc_name}\nID：{project_id[:8]}")
        _log(f"项目注册: {project_name} → {project_id}")
    except Exception as e:
        _log(f"项目注册失败: {e}")
        _send_msg(uid, mid, "项目注册失败，请稍后重试。")
    finally:
        with _pending_project_regs_lock:
            _pending_project_regs.pop(user_key, None)


# ── 消息处理 ─────────────────────────────────────────────────

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
                target=lambda: reply_card(message_id, _welcome()),
                daemon=True,
            ).start()
            return
    except Exception as e:
        _log(f"解析消息异常: {e}\n{traceback.format_exc()}")
        return

    def _process(mid: str, text: str, uid: Optional[str]):
        try:
            lower = text.strip().lower()
            if lower in ("帮助", "help", "?", "？"):
                reply_card(mid, _help())
                return
            if lower in ("hi", "hello", "你好", "嗨", "hey", "在吗", "在不在", "哈喽", "nihao"):
                reply_card(mid, _welcome())
                return

            # ── 检查是否是文档选择 ──
            user_key = uid or mid
            doc_choice = _resolve_doc_choice(text, user_key)
            if doc_choice is not None:
                _handle_doc_choice(mid, uid, user_key, doc_choice)
                return

            # ── 退出追问 ──
            if text.strip() in _EXIT_FOLLOWUP_COMMANDS and _has_planning_context(user_key):
                _clear_planning_context(user_key)
                with _pending_docs_lock:
                    _pending_docs.pop(user_key, None)
                with _pending_project_regs_lock:
                    _pending_project_regs.pop(user_key, None)
                reply_message(mid, "已结束讨论。发新消息即可开始新的对话或规划。")
                return

            # ── 项目纳入请求 ──
            project_reg = _resolve_project_registration(text, user_key)
            if project_reg:
                _handle_project_registration(mid, uid, user_key, project_reg)
                return

            # ── 规划追问（有上下文 + 非显式新规划）──
            if _has_planning_context(user_key) and not _is_explicit_new_planning(text):
                _log(f"追问模式: {text[:60]!r}")
                try:
                    answer = _planning_followup(text, user_key)
                    reply_message(mid, answer)
                except Exception as e:
                    _log(f"追问回复异常: {e}")
                    reply_message(mid, "抱歉，追问时出了点问题。你可以继续提问或发「结束讨论」退出。")
                return

            # ── 普通对话（无规划信号）──
            if not _needs_planning(text):
                _log(f"对话模式: {text[:60]!r}")
                try:
                    answer = _chat_reply(text)
                    reply_message(mid, answer)
                except Exception as e:
                    _log(f"对话回复异常: {e}")
                    reply_message(mid, "抱歉，出了点问题，稍后再试。")
                return

            # ── 比稿模式 ──
            if _is_pitch_request(text):
                agencies, pitch_topic = parse_agency_spec(text)
                _clear_planning_context(user_key)
                if not pitch_topic:
                    _send_msg(uid, mid, "请提供比稿课题，例如：比稿：618 大促营销方案")
                    return
                with _running_lock:
                    if user_key in _running_sessions:
                        reply_card(mid, progress_card(
                            "任务进行中",
                            f"当前主题：**{_running_sessions[user_key][:40]}**\n\n请等当前任务结束后再发起新的。",
                            color="orange",
                        ))
                        return
                    _running_sessions[user_key] = pitch_topic
                agency_names = ", ".join(f"{a.emoji} {a.name}" for a in agencies)
                reply_card(mid, progress_card(
                    "🏆 正在启动 Agency 比稿",
                    f"**课题：**{pitch_topic[:200]}\n"
                    f"**参赛 Agency：**{agency_names}\n\n"
                    f"比稿过程将实时推送到飞书群，约 3-4 分钟。",
                    color="purple",
                ))
                _log(f"启动比稿: topic={pitch_topic[:80]!r} agencies={[a.name for a in agencies]}")
                try:
                    path, planning_outputs, pitch_data = run_pitch(
                        topic=pitch_topic, context="", agencies=agencies,
                    )
                    done_card = result_card(
                        "🏆 比稿完成",
                        fields=[("课题", pitch_topic[:100]), ("Agency", agency_names)],
                        next_actions=["回复数字生成文档", "直接追问比稿内容", "发「结束讨论」退出追问模式"],
                    )
                    if uid:
                        send_card_to_user(uid, done_card)
                    else:
                        reply_card(mid, done_card)

                    short_title = _generate_short_title(pitch_topic)
                    category = "marketing"
                    with _pending_docs_lock:
                        _pending_docs[user_key] = {
                            "topic": pitch_topic,
                            "short_title": short_title,
                            "outputs": planning_outputs,
                            "path": path,
                            "open_id": uid,
                            "category": category,
                            "doc_menu": build_doc_menu(category),
                            "ts": time.time(),
                        }
                    with _planning_contexts_lock:
                        _planning_contexts[user_key] = {
                            "topic": pitch_topic,
                            "outputs": planning_outputs,
                            "history": [],
                            "open_id": uid,
                            "session_path": path,
                            "ts": time.time(),
                        }

                    time.sleep(1)
                    menu_card = _doc_menu_card(category)
                    if uid:
                        send_card_to_user(uid, menu_card)
                    else:
                        reply_card(mid, menu_card)

                    try:
                        from core.events import emit as _emit_event
                        _emit_event("planner", "pitch_completed",
                                    f"比稿完成: {pitch_topic[:50]}",
                                    user_id=uid or "",
                                    meta={"topic": pitch_topic[:100], "path": str(path)})
                    except Exception:
                        pass
                    _log(f"比稿完成: {path}")
                except Exception as e:
                    _log(f"比稿异常: {e}\n{traceback.format_exc()}")
                    err = error_card("比稿执行出错", "内部错误，请稍后重试", suggestions=["重新发送比稿课题再试一次"])
                    if uid:
                        send_card_to_user(uid, err)
                    else:
                        reply_card(mid, err)
                finally:
                    with _running_lock:
                        _running_sessions.pop(user_key, None)
                return

            # ── 新规划：清除旧上下文 ──
            topic, context, mode = _parse_planning_input(text)
            _clear_planning_context(user_key)
            if not topic:
                reply_card(mid, _welcome())
                return
            with _running_lock:
                if user_key in _running_sessions:
                    reply_card(mid, progress_card(
                        "规划进行中",
                        f"当前主题：**{_running_sessions[user_key][:40]}**\n\n请等当前规划结束后再发起新的。",
                        color="orange",
                    ))
                    return
                _running_sessions[user_key] = topic
            reply_card(mid, progress_card(
                "正在启动理性规划",
                f"**主题：**{topic[:200]}\n**模式：**{mode}\n\n规划过程将实时推送到飞书群，完成后我会通知你。",
            ))
            _log(f"启动规划: topic={topic[:80]!r} mode={mode}")
            try:
                path, planning_outputs = run_planning(topic=topic, context=context, mode=mode)
                done_card = result_card(
                    "规划完成",
                    fields=[("主题", topic[:100]), ("模式", mode)],
                    next_actions=["回复数字生成文档", "直接追问规划内容", "发「结束讨论」退出追问模式"],
                )
                if uid:
                    send_card_to_user(uid, done_card)
                else:
                    reply_card(mid, done_card)

                # 生成凝练的文档标题
                short_title = _generate_short_title(topic)

                # 存储规划结果以便后续生成文档
                category = detect_doc_category(topic)
                with _pending_docs_lock:
                    _pending_docs[user_key] = {
                        "topic": topic,
                        "short_title": short_title,
                        "outputs": planning_outputs,
                        "path": path,
                        "open_id": uid,
                        "category": category,
                        "doc_menu": build_doc_menu(category),
                        "ts": time.time(),
                    }

                # 存储规划上下文以便追问
                with _planning_contexts_lock:
                    _planning_contexts[user_key] = {
                        "topic": topic,
                        "outputs": planning_outputs,
                        "history": [],
                        "open_id": uid,
                        "session_path": path,
                        "ts": time.time(),
                    }

                time.sleep(1)
                menu_card = _doc_menu_card(category)
                if uid:
                    send_card_to_user(uid, menu_card)
                else:
                    reply_card(mid, menu_card)

                try:
                    from core.events import emit as _emit_event
                    _emit_event("planner", "planning_completed",
                                f"规划完成: {topic[:50]} ({mode})",
                                user_id=uid or "",
                                meta={"topic": topic[:100], "mode": mode, "path": str(path)})
                except Exception:
                    pass
                _log(f"规划完成: {path}")
            except Exception as e:
                _log(f"规划异常: {e}\n{traceback.format_exc()}")
                err = error_card("规划执行出错", "内部错误，请稍后重试", suggestions=["重新发送主题再试一次"])
                if uid:
                    send_card_to_user(uid, err)
                else:
                    reply_card(mid, err)
            finally:
                with _running_lock:
                    _running_sessions.pop(user_key, None)
        except Exception as e:
            _log(f"处理异常: {e}\n{traceback.format_exc()}")
            try:
                reply_card(mid, error_card("处理出错", "内部错误，请稍后重试", suggestions=["重新发送试试"]))
            except Exception:
                pass

    threading.Thread(target=_process, args=(message_id, user_text, open_id), daemon=True).start()


def _handle_bot_p2p_chat_entered(data) -> None:
    _log("用户打开了与机器人的单聊")
    try:
        open_id = None
        if hasattr(data, "event") and data.event:
            user_id = getattr(data.event, "user_id", None) or getattr(data.event, "operator", None)
            if user_id:
                open_id = getattr(user_id, "open_id", None)
        if open_id:
            send_card_to_user(open_id, _welcome())
    except Exception as e:
        _log(f"发送欢迎卡片异常: {e}")


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
    cli = lark.ws.Client(app_id, app_secret, event_handler=event_handler, log_level=LogLevel.DEBUG, domain="https://open.feishu.cn")
    cli.start()


def main():
    app_id = (os.environ.get("PLANNER_FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or "").strip()
    app_secret = (os.environ.get("PLANNER_FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "请设置环境变量 PLANNER_FEISHU_APP_ID / PLANNER_FEISHU_APP_SECRET\n"
            "（或复用 FEISHU_APP_ID / FEISHU_APP_SECRET）"
        )

    # TODO: 传递凭证应通过配置对象而非修改全局环境变量，同进程多机器人时会冲突
    os.environ["FEISHU_APP_ID"] = app_id
    os.environ["FEISHU_APP_SECRET"] = app_secret

    _log("规划机器人启动")
    print("=" * 60)
    print("理性规划 AI 助手（长连接模式）")
    print()
    print("使用方式：在飞书上给机器人发消息，内容即为规划主题。")
    print()
    print("支持模式：完整规划 | 快速模式 | 分析模式 | 方案模式 | 执行模式")
    print()
    print("断线后将自动重连，无需人工干预。")
    print("=" * 60)

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
                print("\n若持续失败，请检查应用凭证和网络。", file=sys.stderr)
        wait = min(delay, RECONNECT_MAX_DELAY)
        jitter = random.uniform(0, min(5, wait * 0.2))
        wait += jitter
        _log(f"{wait:.1f} 秒后重连…")
        time.sleep(wait)
        delay = min(delay * RECONNECT_MULTIPLIER, RECONNECT_MAX_DELAY)


if __name__ == "__main__":
    main()
