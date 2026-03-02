# -*- coding: utf-8 -*-
"""
助手机器人 —— 你的飞书日常工作伴侣。
=====================================

这是什么？
  在飞书上和这个机器人对话，它能帮你管理备忘、操作日历、
  每天自动推送简报，还能做 AI 对话。

四大功能：
  1. 备忘管理：发「备忘 买牛奶」就记下来，发「备忘列表」就查看
  2. 日程管理：发「明天下午3点开会」自动加入飞书日历
  3. 每日简报：08:00 自动推送今日安排，18:00 推送收尾 checklist
  4. AI 对话 ：其他消息走 DeepSeek 自由对话

消息处理逻辑（按优先级）：
  用户消息 → 帮助？ → 关键词匹配（备忘/待办/清除）
           → AI 意图解析 → 分发到对应处理函数
           → 都不匹配？走自由对话

运行：python3 -m assistant
环境变量：ASSISTANT_FEISHU_APP_ID / ASSISTANT_FEISHU_APP_SECRET（或复用 FEISHU_APP_ID）
"""
import json
import os
import re
import random
import sys
import threading
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional

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
    get_primary_calendar_id,
    create_calendar_event,
    get_minutes_info,
    extract_minute_token,
    create_task,
    get_user_access_token,
)
from core.cards import make_card, welcome_card, action_card, help_card, error_card, progress_card
from core.llm import chat
from memo.intent import parse_intent
from memo.bitable_board import (
    ensure_board as ensure_bitable_board,
    refresh_board as bitable_refresh_board,
    append_board_record as bitable_append_record,
    get_board_url as get_bitable_board_url,
)
from memo.projects import (
    register_project, list_projects as store_list_projects,
    find_project, PROJECT_HEADERS,
)
from memo.finance import (
    add_expense, month_summary, export_month_rows,
    create_budget, find_budget, budget_vs_actual,
    add_goal, update_goal, find_goal_by_keyword, list_goals,
    project_dashboard, available_project_tags,
    EXPENSE_HEADERS, BUDGET_HEADERS, DASHBOARD_HEADERS,
)
from memo.store import (
    add_memo as store_add_memo,
    list_memos as store_list_memos,
    delete_memo_by_index as store_delete_memo_by_index,
    delete_memo_by_content as store_delete_memo_by_content,
    set_memo_category_by_index as store_set_memo_category_by_index,
    complete_memo_by_index as store_complete_by_index,
    complete_memo_by_content as store_complete_by_content,
    list_threads as store_list_threads,
    thread_summary as store_thread_summary,
    get_due_reminders,
    mark_reminder_sent,
    MEMO_CATEGORY_DISPLAY,
    MEMO_CATEGORIES,
)
from memo.threads import extract_thread_tag, detect_thread
from cal.aggregator import aggregate_for_date
from cal.push_target import save_push_target_open_id

_VERIFY_TOKEN = os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
_ENCRYPT_KEY = os.environ.get("FEISHU_ENCRYPT_KEY", "")

# ── 日志 ─────────────────────────────────────────────────────

_bot_log_path: Optional[str] = None
_log_lock = threading.Lock()


def _log(msg: str) -> None:
    global _bot_log_path
    line = f"[AssistantBot] {msg}"
    print(line, file=sys.stderr, flush=True)
    with _log_lock:
        if _bot_log_path is None:
            _bot_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot_assistant.log")
        try:
            with open(_bot_log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except Exception:
            pass


# ── 等待输入状态（用于创建预算等多步流程）──────────────────────
_pending_state: Dict[str, Dict[str, Any]] = {}
_pending_lock = threading.Lock()
_PENDING_STATE_TTL = 1800  # 30 min


def _cleanup_expired_pending():
    """清理过期的 pending 条目（调用方需持有 _pending_lock）。"""
    now = time.time()
    expired = [k for k, v in _pending_state.items()
               if now - v.get("ts", 0) > _PENDING_STATE_TTL]
    for k in expired:
        del _pending_state[k]


def _set_pending(user_key: str, state_type: str, **kwargs):
    with _pending_lock:
        _cleanup_expired_pending()
        _pending_state[user_key] = {"type": state_type, "ts": time.time(), **kwargs}


def _get_pending(user_key: str) -> Optional[Dict[str, Any]]:
    with _pending_lock:
        _cleanup_expired_pending()
        state = _pending_state.get(user_key)
        if state and time.time() - state.get("ts", 0) > _PENDING_STATE_TTL:
            _pending_state.pop(user_key, None)
            return None
        return state


def _clear_pending(user_key: str):
    with _pending_lock:
        _pending_state.pop(user_key, None)


# ── 工具函数 ─────────────────────────────────────────────────

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


def _parse_memo_content_and_category(text: str) -> tuple[str, Optional[str]]:
    """旧版分类解析，保留兼容。"""
    t = (text or "").strip()
    for name, key in MEMO_CATEGORIES.items():
        tag = f"#{name}"
        if tag in t:
            parts = t.split(tag, 1)
            content = (parts[0] + (parts[1] or "")).strip().replace("  ", " ").strip()
            return content or t.replace(tag, "").strip(), key
    return t, None


def _auto_append_board(thread: str, content: str, status: str = "⬜ 进行中"):
    """备忘添加后自动追加到备忘看板 Bitable（静默失败）。"""
    if not thread:
        return
    try:
        from datetime import datetime as _dt
        created = _dt.utcnow().strftime("%Y-%m-%d")
        bitable_append_record(
            thread=thread,
            content=content[:120],
            status=status,
            created=created,
            partition="今日新增",
        )
    except Exception:
        pass


def _split_multi_memos(text: str) -> list[str]:
    """将一条消息拆分为多条备忘。

    支持：换行分隔、数字编号（1. / 1、/ 1) ）、分号/顿号分隔。
    单条内容原样返回（长度为 1 的列表）。
    """
    lines = text.strip().splitlines()
    if len(lines) > 1:
        items = []
        for ln in lines:
            ln = ln.strip()
            ln = re.sub(r"^(\d+)[.、)）]\s*", "", ln)
            if ln:
                items.append(ln)
        if len(items) > 1:
            return items

    parts = re.split(r"[；;]\s*", text.strip())
    if len(parts) > 1:
        return [p.strip() for p in parts if p.strip()]

    return [text.strip()]


def _parse_memo_with_thread(text: str) -> tuple[str, Optional[str], str]:
    """
    从备忘文本中提取内容、旧分类和 #线程 标签。

    「Starboard 策展流程 #creator」→ ("Starboard 策展流程", None, "creator")
    「写周报 #要事」→ ("写周报", "project", "")  (旧分类兼容)
    「对话系统用三层架构」→ ("对话系统用三层架构", None, "催婚")  (自动识别)
    """
    t = (text or "").strip()
    content, old_cat = _parse_memo_content_and_category(t)
    if old_cat:
        return content, old_cat, ""

    content, thread_tag = extract_thread_tag(t)
    if thread_tag:
        return content, None, thread_tag

    existing = [info["thread"] for info in store_list_threads() if info["thread"] != "(未分类)"]
    auto_thread = detect_thread(content, existing_threads=existing)
    return content, None, auto_thread


def _memo_category_tag(memo: dict) -> str:
    key = memo.get("category") or ""
    if not key:
        return ""
    name = MEMO_CATEGORY_DISPLAY.get(key, "")
    return f"[{name}] " if name else ""


# ── 研究报告发送 ─────────────────────────────────────────────

MAX_CARD_SECTION_LEN = 3500
MAX_CARD_TOTAL_LEN = 8000


def _split_report(report: str, max_len: int = MAX_CARD_TOTAL_LEN) -> list[str]:
    """按 markdown 二级标题拆分研究报告，每段不超过 max_len。"""
    import re as _re
    parts = _re.split(r'\n(?=### \d)', report)
    if not parts:
        return [report[:max_len]]

    chunks: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(current) + len(part) + 2 > max_len and current:
            chunks.append(current.strip())
            current = part
        else:
            current = current + "\n\n" + part if current else part
    if current.strip():
        chunks.append(current.strip())

    result = []
    for chunk in chunks:
        if len(chunk) <= max_len:
            result.append(chunk)
        else:
            while chunk:
                result.append(chunk[:max_len])
                chunk = chunk[max_len:]
    return result


def _send_research_report(
    message_id: str,
    open_id: Optional[str],
    topic: str,
    report: str,
) -> None:
    """把研究报告拆分成卡片发送。"""
    chunks = _split_report(report)
    total = len(chunks)

    for i, chunk in enumerate(chunks, 1):
        title = f"🔬 研究报告：{topic[:30]}"
        if total > 1:
            title += f"  [{i}/{total}]"

        card = make_card(title, [{"text": chunk[:MAX_CARD_TOTAL_LEN]}], color="indigo")

        if i == 1:
            if open_id:
                send_card_to_user(open_id, card)
            else:
                reply_card(message_id, card)
        elif open_id:
            send_card_to_user(open_id, card)

        if i < total:
            time.sleep(1.0)

    _log(f"研究报告已发送: {topic[:30]} ({total} 张卡片, {len(report)} 字)")


# ── 团队管理指令 ────────────────────────────────────────────

def _handle_team_command(text: str, open_id: str, mid: str) -> bool:
    """处理团队相关指令。匹配则回复并返回 True，否则返回 False。"""
    from core.team import (
        create_team, join_team, leave_team, get_current_team,
        get_user_teams, switch_team, get_team, list_members,
    )
    t = text.strip()
    t_lower = t.lower()

    # 创建团队 XXX
    m = re.match(r"^创建团队\s+(.+)$", t)
    if m:
        name = m.group(1).strip()
        ok, result = create_team(name, open_id)
        if ok:
            reply_card(mid, action_card(
                "🏢 团队已创建",
                f"**{result['name']}**\n\n"
                f"团队码：**{result['code']}**\n\n"
                f"把团队码分享给成员，对我说「加入团队 {result['code']}」即可加入。",
                hints=["「我的团队」查看详情", "「创建项目 xxx」为团队创建项目"],
                color="green",
            ))
        else:
            reply_message(mid, f"创建失败：{result.get('error', '未知错误')}")
        return True

    # 加入团队 XXX
    m = re.match(r"^加入团队\s+([A-Za-z0-9]+)$", t)
    if m:
        code = m.group(1).strip().upper()
        ok, msg = join_team(code, open_id)
        if ok:
            team = get_team(code)
            bindings_info = ""
            if team and team.get("bindings"):
                links = []
                for rtype, info in team["bindings"].items():
                    url = info.get("url", "")
                    if url:
                        links.append(f"- {rtype}: [打开]({url})")
                if links:
                    bindings_info = "\n\n**团队资源：**\n" + "\n".join(links)
            reply_card(mid, action_card(
                "🏢 加入成功",
                f"{msg}{bindings_info}",
                hints=["「我的团队」查看详情", "「项目列表」查看团队项目"],
                color="green",
            ))
        else:
            reply_message(mid, msg)
        return True

    # 离开团队 (当前团队)
    if t_lower in ("离开团队", "退出团队"):
        team = get_current_team(open_id)
        if not team:
            reply_message(mid, "你当前没有加入任何团队。")
        else:
            ok, msg = leave_team(team["code"], open_id)
            reply_message(mid, msg)
        return True

    # 切换团队
    m = re.match(r"^(?:切换(?:到|为)?|切到)\s*(.+?)(?:团队)?$", t)
    if m:
        from core.team import resolve_team_by_name
        hint = m.group(1).strip()
        matched = resolve_team_by_name(open_id, hint)
        if matched:
            switch_team(open_id, matched["code"])
            reply_card(mid, action_card(
                "🏢 已切换团队",
                f"当前团队：**{matched['name']}**（{len(matched['members'])} 人）",
                hints=["「项目列表」查看团队项目", "「本月花费」查看团队花费"],
                color="blue",
            ))
        else:
            teams = get_user_teams(open_id)
            if teams:
                names = "、".join(f"「{t['name']}」" for t in teams)
                reply_message(mid, f"没找到匹配的团队。你加入的团队有：{names}")
            else:
                reply_message(mid, "你还没有加入任何团队。说「创建团队 名称」或「加入团队 码」")
        return True

    # 我的团队 / 团队信息 / 团队列表
    if t_lower in ("我的团队", "团队信息", "团队列表", "team", "teams"):
        teams = get_user_teams(open_id)
        current = get_current_team(open_id)
        if not teams:
            reply_card(mid, action_card(
                "🏢 团队",
                "你还没有加入任何团队。\n\n"
                "说「**创建团队 名称**」创建一个，\n"
                "或说「**加入团队 码**」加入已有的团队。",
                color="blue",
            ))
        else:
            lines = []
            for t_info in teams:
                marker = " ← 当前" if current and t_info["code"] == current["code"] else ""
                lines.append(
                    f"**{t_info['name']}**{marker}\n"
                    f"  码：`{t_info['code']}`　成员：{len(t_info['members'])} 人"
                )
            hints = ["「切换到 团队名」切换", "「项目列表」查看当前团队项目"]
            reply_card(mid, action_card("🏢 我的团队", "\n\n".join(lines), hints=hints, color="blue"))
        return True

    # 团队码 (查看当前团队码)
    if t_lower in ("团队码",):
        team = get_current_team(open_id)
        if team:
            reply_message(mid, f"当前团队「{team['name']}」的团队码：**{team['code']}**")
        else:
            reply_message(mid, "你当前没有加入任何团队。")
        return True

    return False


# ── 消息处理 ─────────────────────────────────────────────────

def _handle_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    _log("收到消息事件")
    message_id = None
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
        if open_id:
            save_push_target_open_id(open_id)
        _log(f"message_id={message_id!r} open_id={open_id!r} 文本长度={len(user_text)}")
        if not user_text:
            threading.Thread(
                target=lambda: reply_card(message_id, _welcome()),
                daemon=True,
            ).start()
            return
    except Exception as e:
        _log(f"解析消息异常: {e}\n{traceback.format_exc()}")
        return

    def _process(mid: str, text: str, user_open_id: Optional[str]):
        try:
            t = (text or "").strip()

            # 帮助
            if t.lower() in ("帮助", "help", "?", "？"):
                reply_card(mid, _help())
                return

            # 打招呼 / 问「你能做什么」→ 直接回欢迎卡片（否则会走聊天只回文字）
            _greeting = t.lower().strip()
            if _greeting in ("hi", "hello", "你好", "嗨", "在吗", "在么", "hey"):
                reply_card(mid, _welcome())
                return
            if _greeting in ("你可以做什么", "你能做什么", "你能干嘛", "有什么功能", "介绍下自己", "你是谁"):
                reply_card(mid, _welcome())
                return

            # ── 团队指令 ──────────────────────────────────────
            _team_result = _handle_team_command(t, user_open_id or "", mid)
            if _team_result:
                return

            # ── 当前团队码（用于 Bitable 多租户隔离）──
            _current_team_code = ""
            if user_open_id:
                try:
                    from core.team import get_current_team as _gct
                    _ct = _gct(user_open_id)
                    if _ct:
                        _current_team_code = _ct.get("code", "")
                except Exception:
                    pass

            # ── 等待输入状态处理（多步流程）──
            _user_key = user_open_id or mid
            _ps = _get_pending(_user_key)
            if _ps:
                if t.lower() in ("取消", "cancel", "算了"):
                    _clear_pending(_user_key)
                    reply_message(mid, "已取消。")
                    return

                if _ps["type"] == "awaiting_budget_items":
                    proj_name = _ps.get("project", "")
                    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
                    budget_items = []
                    for ln in lines:
                        ln = re.sub(r"^[\d.、)）]\s*", "", ln)
                        parts = re.split(r"\s+", ln.strip(), maxsplit=1)
                        if len(parts) == 2:
                            cat, amt_str = parts
                            try:
                                amt = float(amt_str.replace(",", "").replace("¥", "").replace("￥", ""))
                                budget_items.append({"name": cat, "category": cat, "budget": amt})
                            except ValueError:
                                budget_items.append({"name": ln, "category": "其他", "budget": 0})
                        elif len(parts) == 1:
                            budget_items.append({"name": parts[0], "category": parts[0], "budget": 0})

                    if not budget_items:
                        reply_message(mid, "格式不太对，请每行输入「类别 金额」，例如：营销 50000\n或发「取消」跳过。")
                        return

                    _clear_pending(_user_key)
                    from memo.finance import create_budget as fin_create_budget
                    budget = fin_create_budget(proj_name, budget_items, team_code=_current_team_code)
                    total = budget.get("total_budget", 0)
                    item_lines = [f"- {it['name']}: ¥{it['budget']:,.0f}" for it in budget_items]
                    reply_card(mid, action_card(
                        f"💰 预算已创建 — {proj_name}",
                        f"总预算 **¥{total:,.0f}**\n\n" + "\n".join(item_lines),
                        hints=[f"「记账 描述 金额 #{proj_name}」记账", f"「{proj_name} 预算」查看预算执行"],
                        color="green",
                    ))
                    return

                if _ps["type"] == "awaiting_goal":
                    proj_name = _ps.get("project", "")
                    _clear_pending(_user_key)
                    from memo.finance import add_goal as fin_add_goal
                    goal = fin_add_goal(proj_name, t, "100", "%", team_code=_current_team_code)
                    reply_card(mid, action_card(
                        f"🎯 目标已创建 — {proj_name}",
                        f"**{t}**（目标 100%）",
                        hints=[f"「更新目标 {t[:10]} 50」更新进度", f"「{proj_name} 总览」查看项目全貌"],
                        color="green",
                    ))
                    return

                if _ps["type"] == "awaiting_expense_project":
                    _clear_pending(_user_key)
                    desc = _ps.get("description", "")
                    amt = _ps.get("amount", 0)
                    exp_type = _ps.get("expense_type", "支出")
                    proj_tag = ""
                    if t.lower() not in ("确认", "ok", "跳过", "不归入"):
                        proj_tag = t.strip().lstrip("#")
                    record = add_expense(
                        amount=amt, description=desc,
                        expense_type=exp_type, project=proj_tag,
                        user_open_id=user_open_id or "",
                        team_code=_current_team_code,
                    )
                    tag_info = f"　#{proj_tag}" if proj_tag else ""
                    reply_card(mid, action_card(
                        f"✅ 已记账",
                        f"**{exp_type}** ¥{amt:,.2f} — {desc}{tag_info}\n日期：{record['date']}",
                        hints=["「本月花费」查看月度汇总", "「预算概览 项目名」查预算"],
                        color="green",
                    ))
                    return

            # ── 关键词快速匹配：备忘 ──
            prefixes = (
                "备忘 ", "备忘：", "备忘:", "记一下 ", "记一下：", "记一下:",
                "别忘了 ", "别忘了：", "别忘了:", "任务 ", "任务：", "任务:",
                "待办 ", "待办：", "待办:",
            )
            for prefix in prefixes:
                if t.startswith(prefix):
                    raw_content = t[len(prefix):].strip()
                    if not raw_content:
                        reply_message(mid, "请说一下要记的内容，例如：任务 写周报")
                        return
                    items = _split_multi_memos(raw_content)
                    if len(items) > 1:
                        saved = []
                        for item in items:
                            c, cat, th = _parse_memo_with_thread(item)
                            if c:
                                store_add_memo(c, user_open_id=user_open_id, category=cat, thread=th)
                                _auto_append_board(th, c)
                                tag = f" #{th}" if th else ""
                                saved.append(f"- {c[:60]}{tag}")
                        if saved:
                            reply_card(mid, action_card(
                                f"📝 已记下 {len(saved)} 条备忘",
                                "\n".join(saved),
                                hints=["发「线程」查看工作线程", "发「备忘列表」查看全部"],
                                color="green",
                            ))
                            _log(f"备忘(多条拆分): {len(saved)} 条")
                        return
                    content, category, thread = _parse_memo_with_thread(raw_content)
                    if not content:
                        reply_message(mid, "请说一下要记的内容，例如：任务 写周报")
                        return
                    store_add_memo(content, user_open_id=user_open_id, category=category, thread=thread)
                    _auto_append_board(thread, content)
                    tag_hint = ""
                    if thread:
                        tag_hint = f" #{thread}"
                    elif category:
                        tag_hint = f"（{MEMO_CATEGORY_DISPLAY.get(category, category)}）"
                    reply_card(mid, action_card(
                        f"📝 已记下备忘{tag_hint}",
                        f"**{content[:100]}**",
                        hints=["发「线程」查看工作线程", "发「备忘列表」查看全部"],
                        color="green",
                    ))
                    _log(f"备忘(关键词): 已写入 thread={thread}")
                    return

            if t.lower().startswith("todo ") or t.lower().startswith("todo:"):
                raw_content = t[5:].lstrip(" :").strip()
                if raw_content:
                    content, category, thread = _parse_memo_with_thread(raw_content)
                    store_add_memo(content, user_open_id=user_open_id, category=category, thread=thread)
                    _auto_append_board(thread, content)
                    tag_hint = f" #{thread}" if thread else ""
                    reply_card(mid, action_card(
                        f"📝 已记下备忘{tag_hint}",
                        f"**{content[:100]}**",
                        hints=["发「线程」查看工作线程", "发「备忘列表」查看全部"],
                        color="green",
                    ))
                    _log(f"todo(关键词): 已写入 thread={thread}")
                    return

            if t in ("备忘", "记一下", "别忘了", "任务", "待办"):
                reply_message(mid, "请说「备忘 具体内容」或「任务 具体内容」～")
                return

            # ── 完成备忘 ──
            _CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            def _cn2int(s: str) -> Optional[int]:
                s = s.strip()
                if s.isdigit():
                    return int(s)
                if s in _CN_NUM:
                    return _CN_NUM[s]
                if s.startswith("十") and len(s) == 2 and s[1] in _CN_NUM:
                    return 10 + _CN_NUM[s[1]]
                return None

            _done_prefix = r"(完成|done|搞定|✅|做完了|标记完成|已完成|办好了|弄好了)"

            m_done = re.match(
                rf"^{_done_prefix}\s*第?\s*(\d+)\s*条?\s*$", t, re.IGNORECASE
            )
            if m_done:
                idx = int(m_done.group(2))
                ok, msg_text = store_complete_by_index(idx, user_open_id=user_open_id)
                reply_message(mid, msg_text)
                return

            m_done_cn = re.match(
                rf"^{_done_prefix}\s*第?\s*([一二三四五六七八九十]+)\s*条?\s*$", t, re.IGNORECASE
            )
            if m_done_cn:
                idx = _cn2int(m_done_cn.group(2))
                if idx:
                    ok, msg_text = store_complete_by_index(idx, user_open_id=user_open_id)
                    reply_message(mid, msg_text)
                    return

            m_done_rev = re.match(
                r"^第\s*(\d+|[一二三四五六七八九十]+)\s*条?\s*(完成|搞定|做完了|办好了|弄好了)\s*$", t
            )
            if m_done_rev:
                idx = _cn2int(m_done_rev.group(1))
                if idx:
                    ok, msg_text = store_complete_by_index(idx, user_open_id=user_open_id)
                    reply_message(mid, msg_text)
                    return

            m_done_kw = re.match(
                rf"^{_done_prefix}\s*[：:]?\s*(.+)$", t, re.IGNORECASE
            )
            if m_done_kw:
                keyword = m_done_kw.group(2).strip()
                if not keyword.isdigit() and keyword not in _CN_NUM:
                    ok, msg_text = store_complete_by_content(keyword, user_open_id=user_open_id)
                    reply_message(mid, msg_text)
                    return

            # ── 清除/删除备忘 ──
            _del_idx = None
            m_clear = re.match(
                r"^(清除备忘|删除备忘|删掉|删除|移除|去掉)\s*第?\s*(\d+)\s*条?\s*$", t
            )
            if m_clear:
                _del_idx = m_clear.group(2)
            if not _del_idx:
                m_clear2 = re.match(
                    r"^(清除备忘|删除备忘|删掉|删除|移除|去掉)\s*[：:]\s*(\d+)\s*$", t
                )
                if m_clear2:
                    _del_idx = m_clear2.group(2)
            if not _del_idx:
                m_clear3 = re.match(r"^第\s*(\d+)\s*条?\s*(删掉|删除|移除|去掉)\s*$", t)
                if m_clear3:
                    _del_idx = m_clear3.group(1)
            if _del_idx:
                try:
                    idx = int(_del_idx)
                    ok, msg_text = store_delete_memo_by_index(idx, user_open_id=user_open_id)
                    reply_message(mid, msg_text)
                    return
                except ValueError:
                    pass

            m_clear_kw = re.match(
                r"^(清除备忘|删除备忘|删掉备忘|删掉|删除|移除|去掉)\s*[：:]?\s*(.+)$", t
            )
            if m_clear_kw:
                keyword = m_clear_kw.group(2).strip()
                if not keyword.isdigit():
                    ok, msg_text = store_delete_memo_by_content(keyword, user_open_id=user_open_id)
                    reply_message(mid, msg_text)
                    return

            # ── 设置分类 ──
            m_set_cat = (
                re.match(r"^(?:把)?第\s*(\d+)\s*条\s*(?:标成|设为|标为)\s*(日常|灵感|要事)\s*$", t)
                or re.match(r"^(日常|灵感|要事)\s*[：:]\s*第\s*(\d+)\s*条\s*$", t)
            )
            if m_set_cat:
                if m_set_cat.lastindex == 2 and m_set_cat.group(1).isdigit():
                    idx, cat = int(m_set_cat.group(1)), m_set_cat.group(2)
                else:
                    cat, idx = m_set_cat.group(1), int(m_set_cat.group(2))
                ok, msg_text = store_set_memo_category_by_index(idx, cat, user_open_id=user_open_id)
                reply_message(mid, msg_text)
                return

            # ── 意图解析 ──
            _log("解析意图...")
            intent = parse_intent(text)
            action = intent.get("action", "chat")
            params = intent.get("params") or {}
            reply = intent.get("reply") or ""
            _log(f"意图: action={action}")

            # ── 加日历 ──
            if action == "add_calendar" and user_open_id:
                title = params.get("title") or "日程"
                start_time = params.get("start_time") or ""
                end_time = params.get("end_time") or ""
                if not start_time or not end_time:
                    reply_message(mid, "加日历需要明确开始和结束时间，请再说清楚一点～")
                    return
                cal_token_create = get_user_access_token("calendar_create")
                cal_id = (os.environ.get("FEISHU_CALENDAR_ID") or "").strip()
                if not cal_id:
                    cal_token_get = get_user_access_token("calendar_get")
                    cal_id = get_primary_calendar_id(user_open_id, user_access_token=cal_token_get)
                if not cal_id:
                    reply_message(mid, "无法获取你的日历，请配置 FEISHU_TOKEN_CALENDAR_GET 后重试。")
                    return
                ok, msg_text = create_calendar_event(
                    cal_id, title, start_time, end_time,
                    params.get("description") or "",
                    user_access_token=cal_token_create,
                )
                if not ok and ("access_role" in msg_text.lower() or "no calendar" in msg_text.lower()) and not cal_token_create:
                    msg_text = "往你的个人日历里加日程需要「用户身份」授权。请在 .env 中配置 FEISHU_TOKEN_CALENDAR_CREATE 后再试。"
                reply_message(mid, msg_text)
                return

            # ── 备忘相关 ──
            if action in ("add_todo", "add_task"):
                content = (params.get("title") or params.get("summary") or params.get("content") or text).strip()
                for prefix in ("待办 ", "待办：", "待办:", "任务 ", "任务：", "任务:", "todo "):
                    if content.lower().startswith(prefix) or content.startswith(prefix):
                        content = content[len(prefix):].strip()
                        break
                store_add_memo(content or "未命名", user_open_id=user_open_id)
                reply_message(mid, "已记下备忘～")
                return

            if action in ("add_memo", "add_memos"):
                raw = params.get("content") or text.strip()
                items_from_llm = params.get("items")
                if isinstance(items_from_llm, list) and len(items_from_llm) > 1:
                    memo_items = items_from_llm
                else:
                    memo_items = _split_multi_memos(raw)

                if len(memo_items) > 1:
                    saved = []
                    for item in memo_items:
                        c, cat, th = _parse_memo_with_thread(item.strip() if isinstance(item, str) else str(item))
                        if c:
                            store_add_memo(c, user_open_id=user_open_id, category=cat, thread=th)
                            _auto_append_board(th, c)
                            tag = f" #{th}" if th else ""
                            saved.append(f"- {c[:60]}{tag}")
                    if saved:
                        reply_card(mid, action_card(
                            f"📝 已记下 {len(saved)} 条备忘",
                            "\n".join(saved),
                            hints=["发「线程」查看工作线程", "发「备忘列表」查看全部"],
                            color="green",
                        ))
                    else:
                        reply_message(mid, "请说一下要记的备忘内容～")
                    return

                content, category, thread = _parse_memo_with_thread(raw)
                if not content:
                    reply_message(mid, "请说一下要记的备忘内容～")
                    return
                if not thread:
                    thread = (params.get("thread") or "").strip()
                reminder = (params.get("reminder_date") or "").strip() or None
                store_add_memo(content, user_open_id=user_open_id, reminder_date=reminder, category=category, thread=thread)
                _auto_append_board(thread, content)
                tag_hint = f" #{thread}" if thread else ""
                date_hint = f"（提醒：{reminder}）" if reminder else ""
                reply_message(mid, f"已记下备忘～{tag_hint}{date_hint}")
                return

            if action == "list_memos":
                thread_filter = params.get("thread", "")
                inc_done = params.get("include_done", False)
                memos = store_list_memos(
                    limit=15, user_open_id=user_open_id,
                    thread=thread_filter or None, include_done=inc_done,
                )
                if not memos:
                    reply_card(mid, action_card("📋 暂无备忘", hints=["发「备忘 内容」开始记"], color="blue"))
                    return
                lines = []
                for i, m in enumerate(memos, 1):
                    thread = m.get("thread") or ""
                    tag = f"[#{thread}] " if thread else ""
                    done = "✅ " if m.get("done") else ""
                    lines.append(f"{i}. {done}{tag}{m.get('content', '')}")
                reply_card(mid, action_card(
                    f"📋 备忘列表（{len(memos)} 条）",
                    "\n".join(lines)[:2000],
                    hints=["「完成 3」标记完成", "「完成 买牛奶」按内容完成", "「清除备忘 3」彻底删除"],
                    color="blue",
                ))
                return

            if action == "list_tasks":
                memos = store_list_memos(limit=10, user_open_id=user_open_id)
                if not memos:
                    reply_message(mid, "暂无未完成的备忘。")
                    return
                lines = ["未完成备忘（「完成 序号」标记完成）："]
                for i, m in enumerate(memos, 1):
                    thread = m.get("thread") or ""
                    tag = f"[#{thread}] " if thread else ""
                    lines.append(f"{i}. {tag}{m.get('content', '')}")
                reply_message(mid, "\n".join(lines)[:2000])
                return

            if action == "list_all_memos":
                memos = store_list_memos(limit=200, user_open_id=user_open_id, include_done=True)
                if not memos:
                    reply_message(mid, "暂无备忘。")
                    return
                lines = [f"所有备忘（共 {len(memos)} 条，含已完成）："]
                for i, m in enumerate(memos, 1):
                    thread = m.get("thread") or ""
                    tag = f"[#{thread}] " if thread else ""
                    done = "✅ " if m.get("done") else ""
                    lines.append(f"{i}. {done}{tag}{m.get('content', '')}")
                reply_message(mid, "\n".join(lines)[:4000])
                return

            if action == "list_memos_by_category":
                cat = (params.get("category") or "").strip()
                memos = store_list_memos(limit=200, user_open_id=user_open_id, category=cat)
                if not memos:
                    reply_message(mid, f"暂无「{cat}」类备忘。")
                    return
                lines = [f"「{cat}」类备忘（共 {len(memos)} 条）："]
                for i, m in enumerate(memos, 1):
                    lines.append(f"{i}. {m.get('content', '')}")
                reply_message(mid, "\n".join(lines)[:4000])
                return

            if action == "set_memo_category":
                idx = params.get("index") or params.get("序号")
                cat = (params.get("category") or params.get("分类") or "").strip()
                if not idx or not cat:
                    reply_message(mid, "请说「第3条标成灵感」或「把第2条设为要事」。")
                    return
                try:
                    num = int(idx)
                except (TypeError, ValueError):
                    reply_message(mid, "序号需为数字。")
                    return
                ok, msg_text = store_set_memo_category_by_index(num, cat, user_open_id=user_open_id)
                reply_message(mid, msg_text)
                return

            if action == "delete_memo":
                idx = params.get("index") or params.get("序号")
                keyword = params.get("keyword", "")
                if idx is not None:
                    try:
                        num = int(idx)
                        ok, msg_text = store_delete_memo_by_index(num, user_open_id=user_open_id)
                        reply_message(mid, msg_text)
                        return
                    except (TypeError, ValueError):
                        pass
                if keyword:
                    ok, msg_text = store_delete_memo_by_content(str(keyword), user_open_id=user_open_id)
                    reply_message(mid, msg_text)
                    return
                reply_message(mid, "请说「删除 序号」或「删除 关键词」，例如：删除 3 / 删掉 买牛奶")
                return

            if action == "complete_memo":
                idx = params.get("index")
                keyword = params.get("keyword", "")
                if idx is not None:
                    try:
                        ok, msg_text = store_complete_by_index(int(idx), user_open_id=user_open_id)
                    except (ValueError, TypeError):
                        ok, msg_text = False, "序号需为数字，例如：完成 3"
                elif keyword:
                    ok, msg_text = store_complete_by_content(keyword, user_open_id=user_open_id)
                else:
                    ok, msg_text = False, "请说「完成 3」（按序号）或「完成 买牛奶」（按内容）"
                reply_message(mid, msg_text)
                return

            if action == "complete_task":
                reply_message(mid, "请用「完成 序号」或「完成 关键词」来标记备忘完成～")
                return

            # ── 线程相关 ──
            if action == "list_threads":
                threads = store_list_threads(user_open_id=user_open_id)
                if not threads:
                    reply_card(mid, action_card("📂 暂无工作线程", "发备忘时加 #标签 即可创建线程\n例如：备忘 完成 deck #creator", color="blue"))
                    return
                lines = []
                for info in threads:
                    t = info["thread"]
                    latest = info.get("latest_content", "")[:30]
                    count = info["count"]
                    lines.append(f"**#{t}** ({count}条) — {latest}{'…' if len(info.get('latest_content', '')) > 30 else ''}")
                reply_card(mid, action_card(
                    f"📂 工作线程（{len(threads)} 个）",
                    "\n".join(lines)[:2000],
                    hints=["「#creator进展」查某条线", "「哪条线最久没动」查沉寂"],
                    color="blue",
                ))
                return

            if action == "thread_progress":
                thread_name = (params.get("thread") or "").strip()
                if not thread_name:
                    reply_message(mid, "请说线程名，例如「#creator进展」。")
                    return
                memos = store_list_memos(thread=thread_name, user_open_id=user_open_id, limit=10)
                if not memos:
                    reply_message(mid, f"#{thread_name} 暂无备忘。")
                    return
                lines = [f"**#{thread_name}** 最近动态（{len(memos)} 条）：\n"]
                for i, m in enumerate(memos, 1):
                    date = (m.get("created_at") or "")[:10]
                    lines.append(f"{i}. [{date}] {m.get('content', '')}")
                reply_card(mid, action_card(
                    f"📌 #{thread_name} 进展",
                    "\n".join(lines)[:2000],
                    hints=["「线程」看所有线程", f"「备忘 xxx #{thread_name}」继续记"],
                    color="indigo",
                ))
                return

            if action == "stale_threads":
                summary = store_thread_summary(user_open_id=user_open_id, days=7)
                stale = summary.get("stale", [])
                if not stale:
                    reply_message(mid, "所有线程本周都有动态，没有沉寂的 👍")
                    return
                lines = ["本周没有新备忘的线程：\n"]
                for s in stale[:8]:
                    lines.append(f"💤 **#{s['thread']}** — {s['days_silent']}天没动了（共{s['total']}条备忘）")
                reply_card(mid, action_card(
                    "💤 沉寂线程",
                    "\n".join(lines)[:2000],
                    hints=["发「#xxx进展」查某条线详情"],
                    color="yellow",
                ))
                return

            if action == "weekly_report":
                summary = store_thread_summary(user_open_id=user_open_id, days=7)
                active = summary.get("active", {})
                stale = summary.get("stale", [])
                lines = ["📊 **本周工作线程概览**\n"]
                if active:
                    lines.append("🔥 **活跃**")
                    for t, info in sorted(active.items(), key=lambda x: x[1]["count"], reverse=True):
                        if t == "(未分类)":
                            continue
                        preview = "、".join(info["items"][:2])
                        lines.append(f"  **#{t}** ({info['count']}条) — {preview}")
                    uncat = active.get("(未分类)")
                    if uncat:
                        lines.append(f"  _(未分类 {uncat['count']}条)_")
                if stale:
                    lines.append("\n💤 **沉寂**")
                    for s in stale[:5]:
                        lines.append(f"  **#{s['thread']}** — {s['days_silent']}天没动")
                if not active and not stale:
                    lines.append("本周暂无备忘记录。")
                reply_card(mid, action_card(
                    "📊 周报",
                    "\n".join(lines)[:2000],
                    hints=["「#xxx进展」查某条线", "「线程」查所有"],
                    color="indigo",
                ))
                return

            # ── 月报 ──
            if action == "monthly_report":
                month = (params.get("month") or "").strip()
                reply_card(mid, progress_card("正在生成月报", f"AI 汇总线程+项目+财务…", color="indigo"))
                try:
                    from cal.daily_brief import generate_monthly_report
                    report = generate_monthly_report(month=month, user_open_id=user_open_id)
                    if not report:
                        report = "暂无足够数据生成月报。"
                    if len(report) > 3500:
                        parts = [report[i:i+3500] for i in range(0, len(report), 3500)]
                        for i, part in enumerate(parts):
                            title = "📊 月度报告" if i == 0 else f"📊 月度报告（续 {i+1}）"
                            reply_card(mid, action_card(title, part, color="indigo"))
                    else:
                        reply_card(mid, action_card("📊 月度报告", report, color="indigo"))
                except Exception as e:
                    _log(f"月报生成失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("月报生成失败", "生成失败，请稍后重试。"))
                return

            # ── 联网研究 ──
            if action == "research":
                topic = (params.get("topic") or text).strip()
                if not topic:
                    reply_message(mid, "请说要研究什么，例如：研究 Character.ai 增长机制")
                    return
                reply_card(mid, progress_card(
                    "正在研究",
                    f"**课题：**{topic[:100]}\n\n"
                    "正在多来源搜索、交叉验证、分析机制……\n"
                    "预计 1–3 分钟，完成后发送完整报告。",
                    color="indigo",
                ))
                try:
                    from research.researcher import Researcher
                    researcher = Researcher()
                    report = researcher.research(topic, verbose=False)
                except Exception as e:
                    _log(f"研究失败: {e}\n{traceback.format_exc()}")
                    if user_open_id:
                        send_card_to_user(user_open_id, error_card(
                            "研究失败", "生成失败，请稍后重试。",
                            suggestions=["换个说法重试", "发「帮助」查看指令"],
                        ))
                    return

                _send_research_report(mid, user_open_id, topic, report)
                return

            # ── 导出线程看板 ──
            if action == "export_board":
                thread_filter = (params.get("thread") or "").strip()
                title = f"📋 线程看板 — #{thread_filter}" if thread_filter else "📋 线程看板"
                reply_card(mid, progress_card("正在生成看板", title, color="blue"))
                try:
                    ok_b, url_or_err, board_stats = bitable_refresh_board(
                        user_open_id=user_open_id,
                        thread=thread_filter or None,
                    )
                    if not ok_b:
                        _log(f"看板刷新失败: {url_or_err}")
                        reply_card(mid, error_card("生成看板失败", "操作失败，请稍后重试。"))
                        return

                    if not board_stats or sum(board_stats.values()) == 0:
                        hint = f"线程 #{thread_filter} 下没有备忘" if thread_filter else "还没有备忘数据"
                        reply_card(mid, action_card("📋 看板为空", hint,
                            hints=["发「备忘 xxx #线程」添加内容", "发「线程」查看现有线程"],
                            color="blue"))
                        return

                    board_url = url_or_err or get_bitable_board_url()
                    _stats_line = (
                        f"今日新增 {board_stats.get('today', 0)} 条 | "
                        f"本周进行中 {board_stats.get('week', 0)} 条 | "
                        f"等待跟进 {board_stats.get('stale', 0)} 条 | "
                        f"已完成 {board_stats.get('done', 0)} 条"
                    )

                    reply_card(mid, action_card(
                        "📋 线程看板已刷新",
                        f"**{title}**\n\n"
                        f"[点击打开看板]({board_url})\n\n"
                        f"{_stats_line}"
                        + ("\n\n新增备忘会自动追加到此看板" if thread_filter else ""),
                        hints=["数据来自你的备忘，可在飞书中编辑", "再发「看板」可刷新"],
                        color="green",
                    ))
                except Exception as e:
                    _log(f"生成线程看板失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("生成看板失败", "操作失败，请稍后重试。"))
                return

            # ── 创建项目 ──
            if action == "create_project":
                proj_name = (params.get("name") or "").strip()
                if not proj_name:
                    reply_message(mid, "请说项目名称，例如：创建项目 Q2营销")
                    return
                existing = find_project(proj_name)
                if existing:
                    _url = existing.get("bitable_url") or existing.get("url", "")
                    reply_card(mid, action_card(
                        "📋 项目已存在",
                        f"**{existing['name']}**\n[打开项目管理中心]({_url})",
                        hints=[f"直接说「{existing['name']} 加任务 xxx」添加内容"],
                        color="blue",
                    ))
                    return
                reply_card(mid, progress_card("正在创建项目", f"**{proj_name}**", color="blue"))
                try:
                    from memo.bitable_hub import ensure_hub
                    ensure_hub(team_code=_current_team_code)
                    register_project(
                        name=proj_name,
                        spreadsheet_token="",
                        sheet_id="",
                        url="",
                        created_by=user_open_id or "",
                        team_code=_current_team_code,
                    )
                    proj = find_project(proj_name)
                    hub_url = (proj or {}).get("bitable_url", "")
                    _user_key = user_open_id or mid
                    _set_pending(_user_key, "awaiting_budget_items", project=proj_name)
                    reply_card(mid, action_card(
                        "📋 项目已创建",
                        f"**{proj_name}**\n\n"
                        + (f"[打开项目管理中心]({hub_url})\n\n" if hub_url else "")
                        + "**接下来设置预算**（每行：类别 金额）：\n"
                        "> 营销 50000\n"
                        "> 设计 10000\n"
                        "> 差旅 5000\n\n"
                        "直接发送预算项，或发「取消」跳过。",
                        hints=[
                            f"「{proj_name} 加任务 xxx」添加任务",
                            "发飞书妙记链接可直接归档到资料库",
                        ],
                        color="green",
                    ))
                except Exception as e:
                    _log(f"创建项目失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("创建项目失败", "操作失败，请稍后重试。"))
                return

            # ── 项目列表 ──
            if action == "list_projects":
                projects = store_list_projects()
                if not projects:
                    reply_card(mid, action_card(
                        "📋 暂无项目",
                        "还没有创建过项目表。",
                        hints=["说「创建项目 xxx」开始"],
                        color="blue",
                    ))
                    return
                lines = []
                from memo.bitable_hub import get_hub_url as _get_hub_url
                _hub = _get_hub_url(team_code=_current_team_code)
                for i, p in enumerate(projects, 1):
                    _purl = p.get("bitable_url") or p.get("url", "")
                    lines.append(f"{i}. **{p['name']}**　_{p['created_at'][:10]}_")
                if _hub:
                    lines.append(f"\n[打开项目管理中心]({_hub})")
                reply_card(mid, action_card(
                    f"📋 项目列表（{len(projects)} 个）",
                    "\n".join(lines),
                    hints=["「项目名 加任务 xxx」添加内容", "发妙记链接可归档到资料库"],
                    color="blue",
                ))
                return

            # ── 加任务到项目 ──
            if action == "add_project_task":
                proj_name = (params.get("project") or "").strip()
                task_text = (params.get("task") or "").strip()
                if not proj_name or not task_text:
                    reply_message(mid, "格式：Q2营销 加任务 写推广方案\n或：加任务 写推广方案 到 Q2营销")
                    return
                proj = find_project(proj_name)
                if not proj:
                    reply_card(mid, error_card(
                        "未找到项目",
                        f"没有名为「{proj_name}」的项目",
                        suggestions=[f"先「创建项目 {proj_name}」", "「项目列表」查看已有项目"],
                    ))
                    return
                try:
                    from memo.bitable_hub import add_task as _bt_add_task, get_hub_url
                    assignee = ""
                    import re as _re
                    m_at = _re.search(r"[@＠]([\w\u4e00-\u9fff]+)", task_text)
                    if m_at:
                        assignee = m_at.group(1)
                        task_text = task_text[:m_at.start()].strip()
                    ok, msg = _bt_add_task(
                        project=proj["name"], task=task_text,
                        source="手动添加", assignee=assignee,
                        team_code=_current_team_code,
                    )
                    hub_url = proj.get("bitable_url") or get_hub_url(team_code=_current_team_code)
                    if ok:
                        reply_card(mid, action_card(
                            "✅ 任务已添加",
                            f"**{proj['name']}** ← {task_text}"
                            + (f"\n负责人：{assignee}" if assignee else ""),
                            hints=[f"[打开项目管理中心]({hub_url})"] if hub_url else [],
                            color="green",
                        ))
                    else:
                        _log(f"添加任务失败: {msg}")
                        reply_card(mid, error_card("添加任务失败", "操作失败，请稍后重试。"))
                except Exception as e:
                    _log(f"加任务失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("添加任务失败", "操作失败，请稍后重试。"))
                return

            # ── 导入飞书妙记 ──
            if action == "import_minutes":
                raw_text = params.get("text") or text
                proj_name = (params.get("project") or "").strip()
                token = extract_minute_token(raw_text)
                if not token:
                    reply_message(mid, "没有识别到妙记链接，请发送完整的飞书妙记链接。")
                    return
                ok, info = get_minutes_info(token)
                if not ok:
                    _log(f"获取妙记失败: {info}")
                    reply_card(mid, error_card("获取妙记失败", "操作失败，请稍后重试。",
                        suggestions=["检查链接是否正确", "确认 bot 有妙记阅读权限"]))
                    return
                minutes_title = info.get("title", "未知会议")
                minutes_dur = info.get("duration", "")
                minutes_url = info.get("url", "")
                if not proj_name:
                    projects = store_list_projects()
                    if projects:
                        proj_hints = "、".join(p["name"] for p in projects[:5])
                        reply_card(mid, action_card(
                            f"🎬 识别到妙记：{minutes_title}",
                            f"时长：{minutes_dur}\n\n要归档到哪个项目？\n现有项目：{proj_hints}\n\n"
                            f"回复：**归档到 项目名**",
                            color="blue",
                        ))
                    else:
                        reply_card(mid, action_card(
                            f"🎬 识别到妙记：{minutes_title}",
                            f"时长：{minutes_dur}\n\n还没有项目，先创建一个：\n**创建项目 项目名**",
                            color="blue",
                        ))
                    return
                proj = find_project(proj_name)
                if not proj:
                    reply_card(mid, error_card("未找到项目", f"没有「{proj_name}」",
                        suggestions=[f"先「创建项目 {proj_name}」"]))
                    return
                try:
                    from memo.bitable_hub import add_resource as _bt_add_resource, get_hub_url
                    note = f"时长：{minutes_dur}" if minutes_dur else ""
                    ok2, msg = _bt_add_resource(
                        project=proj["name"],
                        name=minutes_title,
                        res_type="飞书妙记",
                        link=minutes_url,
                        source="自动记录",
                        note=note,
                        team_code=_current_team_code,
                    )
                    hub_url = proj.get("bitable_url") or get_hub_url(team_code=_current_team_code)
                    if ok2:
                        reply_card(mid, action_card(
                            "✅ 妙记已归档到资料库",
                            f"**{minutes_title}** → {proj['name']}\n\n"
                            + (f"[打开项目管理中心]({hub_url})\n\n" if hub_url else "")
                            + "粘贴会议纪要内容，我可以自动提取 action items",
                            color="green",
                        ))
                    else:
                        _log(f"归档失败: {msg}")
                        reply_card(mid, error_card("归档失败", "操作失败，请稍后重试。"))
                except Exception as e:
                    _log(f"导入妙记失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("导入妙记失败", "操作失败，请稍后重试。"))
                return

            # ── 导入内容到项目（LLM 通用格式识别）──
            if action == "import_content":
                proj_name = (params.get("project") or "").strip()
                content = (params.get("content") or text).strip()
                if not proj_name:
                    projects = store_list_projects()
                    if projects:
                        proj_hints = "、".join(p["name"] for p in projects[:5])
                        reply_card(mid, action_card(
                            "📋 导入到哪个项目？",
                            f"现有项目：{proj_hints}\n\n回复：**导入到 项目名**",
                            hints=["或先「创建项目 xxx」新建一个"],
                            color="blue",
                        ))
                    else:
                        reply_message(mid, "还没有项目，先说「创建项目 xxx」新建一个。")
                    return
                if not content or len(content) < 5:
                    reply_message(mid, "请粘贴要导入的内容（表格、列表、会议纪要、任意格式均可）。")
                    return
                proj = find_project(proj_name)
                if not proj:
                    reply_card(mid, error_card("未找到项目", f"没有「{proj_name}」",
                        suggestions=[f"先「创建项目 {proj_name}」"]))
                    return
                reply_card(mid, progress_card("正在识别内容", f"AI 解析中 → **{proj['name']}**", color="blue"))
                try:
                    extract_prompt = (
                        "从以下内容中提取所有任务/议题/事项。内容可能是：\n"
                        "- Markdown 表格\n- 纯文本列表\n- 会议纪要\n- 项目计划\n- 任意格式\n\n"
                        "每条输出一行 JSON：\n"
                        "{\"task\": \"任务描述\", \"source\": \"来源说明(如:会议纪要/表格导入/项目计划)\", "
                        "\"assignee\": \"负责人或空\", \"status\": \"待开始/进行中/已完成\", "
                        "\"priority\": \"P0/P1/P2或空\", \"due\": \"截止日期或空\", \"note\": \"备注或空\"}\n\n"
                        "要求：\n"
                        "- 尽量保留原始信息，不要丢失字段\n"
                        "- 如果原文有表头，根据表头映射字段\n"
                        "- 如果是自由文本，提取其中的任务/决议/待办\n"
                        "- 只输出 JSON 行，不要其他文字。没有任务就输出 []\n\n"
                        f"内容：\n{content[:4000]}"
                    )
                    raw = chat(extract_prompt)
                    import json as _json
                    items = []
                    if raw and raw.strip().startswith("["):
                        items = _json.loads(raw.strip())
                    else:
                        for line in (raw or "").strip().split("\n"):
                            line = line.strip()
                            if line.startswith("{"):
                                try:
                                    items.append(_json.loads(line))
                                except _json.JSONDecodeError:
                                    pass
                    if not items:
                        reply_card(mid, action_card(
                            "📋 未识别到内容",
                            "AI 没有从文本中提取到任务/事项。\n可以手动添加：\n"
                            f"**{proj['name']} 加任务 xxx**",
                            color="blue",
                        ))
                        return
                    from memo.bitable_hub import add_task as _bt_add_task, get_hub_url
                    success_count = 0
                    for it in items:
                        _ok, _ = _bt_add_task(
                            project=proj["name"],
                            task=it.get("task", ""),
                            source=it.get("source", "导入"),
                            assignee=it.get("assignee", ""),
                            status=it.get("status", "待开始"),
                            priority=it.get("priority", ""),
                            due=it.get("due", ""),
                            note=it.get("note", ""),
                            team_code=_current_team_code,
                        )
                        if _ok:
                            success_count += 1
                    hub_url = proj.get("bitable_url") or get_hub_url(team_code=_current_team_code)
                    if success_count > 0:
                        preview = items[:10]
                        task_list = "\n".join(
                            f"- {it.get('task', '')}"
                            + (f"（{it.get('assignee', '')}）" if it.get("assignee") else "")
                            for it in preview
                        )
                        if len(items) > 10:
                            task_list += f"\n- …还有 {len(items) - 10} 条"
                        reply_card(mid, action_card(
                            f"✅ 已导入 {success_count} 条到 {proj['name']}",
                            task_list
                            + (f"\n\n[打开项目管理中心]({hub_url})" if hub_url else ""),
                            color="green",
                        ))
                    else:
                        _log("导入内容写入失败: 所有记录写入 Bitable 失败")
                        reply_card(mid, error_card("写入失败", "操作失败，请稍后重试。"))
                except Exception as e:
                    _log(f"导入内容失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("导入内容失败", "操作失败，请稍后重试。"))
                return

            # ── 记账（含项目标签提示）──
            if action == "add_expense":
                desc = (params.get("description") or "").strip()
                amt_str = (params.get("amount") or "").strip()
                exp_type = (params.get("type") or "支出").strip()
                proj_tag = (params.get("project") or "").strip()
                if not desc or not amt_str:
                    reply_message(mid, "格式：记账 午餐 35\n或：支出 办公用品 200 #Q2营销")
                    return
                try:
                    amt = float(amt_str)
                except ValueError:
                    reply_message(mid, f"金额「{amt_str}」不是数字，请重新输入。")
                    return
                if not proj_tag:
                    tags = available_project_tags()
                    if tags:
                        tag_list = "　".join(f"`#{t}`" for t in tags[:8])
                        _user_key = user_open_id or mid
                        _set_pending(_user_key, "awaiting_expense_project",
                                     description=desc, amount=amt, expense_type=exp_type)
                        reply_card(mid, action_card(
                            f"💰 {exp_type} ¥{amt:.0f} — {desc}",
                            f"要归入哪个项目？\n{tag_list}\n\n"
                            f"回复 **#项目名** 归入项目，或回复 **确认** 不归入项目直接记账。",
                            color="blue",
                        ))
                        return
                record = add_expense(
                    amount=amt, description=desc,
                    expense_type=exp_type, project=proj_tag,
                    user_open_id=user_open_id or "",
                    team_code=_current_team_code,
                )
                tag_info = f"　#{proj_tag}" if proj_tag else ""
                reply_card(mid, action_card(
                    f"✅ 已记账",
                    f"**{exp_type}** ¥{amt:,.2f} — {desc}{tag_info}\n日期：{record['date']}",
                    hints=["「本月花费」查看月度汇总", "「预算概览 项目名」查预算"],
                    color="green",
                ))
                return

            # ── 批量记账（LLM 提取任意格式费用）──
            if action == "import_expenses":
                raw_content = (params.get("content") or text).strip()
                proj_tag = (params.get("project") or "").strip()
                if not raw_content or len(raw_content) < 5:
                    reply_message(mid, "请发送费用数据（表格、列表或任意格式），我会自动识别。")
                    return
                reply_card(mid, progress_card("正在识别费用", "AI 解析中…", color="blue"))
                try:
                    extract_prompt = (
                        "从以下文本中提取所有费用/支出/收入记录。\n"
                        "每条输出一行 JSON：{\"date\": \"YYYY-MM-DD或空\", \"category\": \"类别\", "
                        "\"description\": \"描述\", \"amount\": 数字, \"type\": \"支出或收入\"}\n"
                        "类别从以下选择：人力、营销、设计、技术、办公、差旅、餐饮、其他\n"
                        "金额必须是纯数字。如果原文没有日期就留空。\n"
                        "只输出 JSON 行，不要其他文字。如果没有费用数据就输出 []\n\n"
                        f"文本：\n{raw_content[:4000]}"
                    )
                    raw = chat(extract_prompt)
                    import json as _json
                    items = []
                    if raw and raw.strip().startswith("["):
                        items = _json.loads(raw.strip())
                    else:
                        for line in (raw or "").strip().split("\n"):
                            line = line.strip()
                            if line.startswith("{"):
                                try:
                                    items.append(_json.loads(line))
                                except _json.JSONDecodeError:
                                    pass
                    if not items:
                        reply_card(mid, action_card(
                            "💰 未识别到费用",
                            "AI 没有从内容中提取到费用记录。\n"
                            "请确认内容包含金额信息，或尝试：**记账 描述 金额**",
                            color="blue",
                        ))
                        return
                    records = []
                    for it in items:
                        try:
                            amt = float(it.get("amount", 0))
                        except (ValueError, TypeError):
                            continue
                        if amt <= 0:
                            continue
                        r = add_expense(
                            amount=amt,
                            description=it.get("description", ""),
                            category=it.get("category", "其他"),
                            project=proj_tag or "",
                            date=it.get("date", ""),
                            expense_type=it.get("type", "支出"),
                            user_open_id=user_open_id or "",
                            team_code=_current_team_code,
                        )
                        records.append(r)
                    if not records:
                        reply_message(mid, "提取到的记录金额均无效，请检查数据。")
                        return
                    total = sum(r["amount"] for r in records)
                    detail_lines = []
                    for r in records[:15]:
                        tag = f" #{r['project']}" if r.get("project") else ""
                        detail_lines.append(f"- {r['type']} ¥{r['amount']:,.0f} {r['description']}{tag}")
                    if len(records) > 15:
                        detail_lines.append(f"- …还有 {len(records) - 15} 条")
                    reply_card(mid, action_card(
                        f"✅ 已导入 {len(records)} 笔，共 ¥{total:,.2f}",
                        "\n".join(detail_lines),
                        hints=["「本月花费」查看月度汇总", "「预算概览 项目名」查预算"],
                        color="green",
                    ))
                except Exception as e:
                    _log(f"批量记账失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("导入费用失败", "操作失败，请稍后重试。"))
                return

            # ── 月度花费 ──
            if action == "month_expenses":
                month = (params.get("month") or "").strip()
                try:
                    summary = month_summary(month)
                    if summary["count"] == 0:
                        reply_card(mid, action_card(
                            f"💰 {summary['month']} 暂无记录",
                            "还没有记账数据。\n说 **记账 描述 金额** 开始记账。",
                            color="blue",
                        ))
                        return
                    lines = [f"**{summary['month']}** 共 {summary['count']} 笔\n"]
                    lines.append(f"支出：**¥{summary['total_expense']:,.2f}**")
                    if summary["total_income"] > 0:
                        lines.append(f"收入：¥{summary['total_income']:,.2f}")
                    if summary["by_category"]:
                        lines.append("\n**按类别：**")
                        for cat, val in summary["by_category"].items():
                            lines.append(f"- {cat}　¥{val:,.0f}")
                    if summary["by_project"]:
                        lines.append("\n**按项目：**")
                        for proj, val in summary["by_project"].items():
                            lines.append(f"- {proj}　¥{val:,.0f}")
                    from memo.bitable_hub import get_hub_url as _get_hub_url
                    _hub = _get_hub_url(team_code=_current_team_code)
                    if _hub:
                        lines.append(f"\n[打开项目管理中心]({_hub})")
                    reply_card(mid, action_card(
                        f"💰 {summary['month']} 月度花费",
                        "\n".join(lines),
                        hints=["「预算概览 项目名」看预算执行", "「项目名 总览」看全维度"],
                        color="blue",
                    ))
                except Exception as e:
                    _log(f"月度花费失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("查询失败", "查询失败，请稍后重试。"))
                return

            # ── 创建预算 ──
            if action == "create_budget":
                proj_name = (params.get("project") or "").strip()
                if not proj_name:
                    reply_message(mid, "请说项目名称，例如：创建预算 Q2营销")
                    return
                existing = find_budget(proj_name)
                if existing:
                    reply_card(mid, action_card(
                        "💰 预算已存在",
                        f"**{existing['project']}** 总预算 ¥{existing['total_budget']:,.0f}",
                        hints=[f"「{proj_name} 预算」查看详情", f"「{proj_name} 总览」看全维度"],
                        color="blue",
                    ))
                    return
                _user_key = user_open_id or mid
                _set_pending(_user_key, "awaiting_budget_items", project=proj_name)
                reply_card(mid, action_card(
                    f"💰 创建预算 — {proj_name}",
                    "请发送预算项（每行一项），格式：\n"
                    "> 类别 金额\n\n"
                    "例如：\n"
                    "> 营销 50000\n"
                    "> 设计 10000\n"
                    "> 差旅 5000\n\n"
                    "发「取消」跳过。",
                    color="blue",
                ))
                return

            # ── 预算概览 ──
            if action == "budget_overview":
                proj_name = (params.get("project") or "").strip()
                if not proj_name:
                    reply_message(mid, "请说项目名称，例如：预算概览 Q2营销")
                    return
                try:
                    headers, rows, summary = budget_vs_actual(proj_name)
                    if "error" in summary:
                        reply_card(mid, error_card("预算概览", summary["error"],
                            suggestions=[f"先「创建预算 {proj_name}」"]))
                        return
                    lines = [
                        f"总预算：**¥{summary['total_budget']:,.0f}**\n"
                        f"已花费：**¥{summary['total_actual']:,.0f}**\n"
                        f"剩余：¥{summary['total_remaining']:,.0f}　使用率 {summary['usage_pct']}\n"
                    ]
                    lines.append("| 预算项 | 预算 | 实际 | 剩余 | 使用率 |")
                    lines.append("|--------|------|------|------|--------|")
                    for r in rows:
                        lines.append(f"| {r[0]} | ¥{r[2]} | ¥{r[3]} | ¥{r[4]} | {r[5]} |")
                    reply_card(mid, action_card(
                        f"💰 {proj_name} 预算概览",
                        "\n".join(lines),
                        hints=[f"「{proj_name} 总览」看全维度", "「本月花费」看月度汇总"],
                        color="blue",
                    ))
                except Exception as e:
                    _log(f"预算概览失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("查询失败", "查询失败，请稍后重试。"))
                return

            # ── 设目标 ──
            if action == "add_goal":
                proj_name = (params.get("project") or "").strip()
                goal_name = (params.get("name") or "").strip()
                target = (params.get("target") or "").strip()
                unit = (params.get("unit") or "").strip()
                if not proj_name or not goal_name or not target:
                    reply_message(mid, "格式：Q2营销 设目标 新增用户 10000 人")
                    return
                goal = add_goal(proj_name, goal_name, target, unit, team_code=_current_team_code)
                reply_card(mid, action_card(
                    "🎯 目标已设定",
                    f"**{proj_name}**\n{goal_name}：{target}{unit}\n\n"
                    f"说 **更新目标 {goal_name} 当前值** 更新进度",
                    hints=[f"「{proj_name} 总览」看全维度仪表盘"],
                    color="green",
                ))
                return

            # ── 更新目标 ──
            if action == "update_goal":
                kw = (params.get("keyword") or "").strip()
                current = (params.get("current") or "").strip()
                if not kw or not current:
                    reply_message(mid, "格式：更新目标 新增用户 7500")
                    return
                goal = find_goal_by_keyword(kw)
                if not goal:
                    reply_message(mid, f"没找到包含「{kw}」的目标。")
                    return
                ok, msg = update_goal(goal["id"], current=current)
                if ok:
                    try:
                        pct = f"{float(current) / float(goal['target']) * 100:.0f}%"
                    except (ValueError, ZeroDivisionError):
                        pct = "-"
                    reply_card(mid, action_card(
                        "🎯 目标已更新",
                        f"**{goal['project']}** — {goal['name']}\n"
                        f"进度：{current}/{goal['target']}{goal.get('unit','')}　({pct})",
                        color="green",
                    ))
                else:
                    reply_message(mid, msg)
                return

            # ── 项目总览（仪表盘）──
            if action == "project_dashboard":
                proj_name = (params.get("project") or "").strip()
                if not proj_name:
                    reply_message(mid, "请说项目名称，例如：Q2营销 总览")
                    return
                try:
                    headers, rows = project_dashboard(proj_name)
                    lines = []
                    lines.append("| 维度 | 指标 | 目标 | 当前 | 进度 | 状态 |")
                    lines.append("|------|------|------|------|------|------|")
                    for r in rows:
                        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |")
                    from memo.bitable_hub import get_hub_url as _get_hub_url
                    proj = find_project(proj_name)
                    _hub = (proj.get("bitable_url") if proj else None) or _get_hub_url(team_code=_current_team_code)
                    proj_link = f"\n\n[打开项目管理中心]({_hub})" if _hub else ""
                    reply_card(mid, action_card(
                        f"📊 {proj_name} 总览",
                        "\n".join(lines) + proj_link,
                        hints=["「记账 描述 金额 #项目」记一笔", f"「{proj_name} 设目标 xxx 数值」"],
                        color="indigo",
                    ))
                except Exception as e:
                    _log(f"项目总览失败: {e}\n{traceback.format_exc()}")
                    reply_card(mid, error_card("查询失败", "查询失败，请稍后重试。"))
                return

            # ── 查日程 ──
            if action == "get_schedule":
                date_param = (params.get("date") or "today").strip()
                agg = aggregate_for_date(date_param, user_open_id=user_open_id)
                feishu = agg.get("feishu_events") or []
                google_ev = agg.get("google_events") or []
                memos = agg.get("memos") or []
                lines = [f"【{agg['date']}】"]
                if feishu:
                    lines.append("飞书日程：")
                    for e in feishu:
                        s = e.get("summary") or "(无标题)"
                        st = e.get("start") or {}
                        ts = st.get("timestamp") if isinstance(st, dict) else ""
                        lines.append(f"  - {s}" + (f" 时间戳:{ts}" if ts else ""))
                if google_ev:
                    lines.append("Google 日程：")
                    for e in google_ev:
                        lines.append(f"  - {e.get('summary', '')} {e.get('start', '')}～{e.get('end', '')}")
                if memos:
                    lines.append("备忘：")
                    for m in memos:
                        lines.append(f"  - {m.get('content', '')}")
                if not feishu and not google_ev and not memos:
                    reply_card(mid, action_card(
                        f"📅 {agg['date']} 暂无安排",
                        "今天是空白的一天，可以安心安排～",
                        hints=["发「明天下午3点开会」加日程", "发「备忘 xxx」记事情"],
                        color="blue",
                    ))
                    return
                raw_text = "\n".join(lines)
                from core.skill_router import enrich_prompt
                system_prompt = enrich_prompt(
                    "你是日程助手。根据下面汇总的日程与备忘，给用户一段简洁友好的总结与建议，控制在 200 字内。",
                    user_text=raw_text, bot_type="assistant",
                )
                try:
                    reply_text = chat(raw_text, system_prompt=system_prompt) or raw_text
                except Exception:
                    reply_text = raw_text
                reply_card(mid, action_card(
                    f"📅 {agg['date']} 日程概览",
                    reply_text[:2000],
                    hints=["发「明天」看明日安排", "发时间+事项可加日历"],
                    color="blue",
                ))
                return

            # ── 普通聊天 ──
            if action == "chat" and reply:
                reply_text = reply
            else:
                from core.skill_router import enrich_prompt
                system_prompt = enrich_prompt(
                    "你是飞书里的备忘与日程助手。可以帮用户记备忘、加日历、查日程。请用简洁友好的中文回复。",
                    user_text=text, bot_type="assistant",
                )
                try:
                    reply_text = chat(text, system_prompt=system_prompt) or "（暂无回复）"
                except Exception:
                    reply_text = "（AI 暂时不可用，请稍后再试）"
            reply_message(mid, reply_text[:2000])

        except Exception as e:
            _log(f"处理异常: {e}\n{traceback.format_exc()}")
            try:
                reply_card(mid, error_card("处理出错", "内部错误，请稍后重试", suggestions=["重新发送试试", "发「帮助」看指令"]))
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
            save_push_target_open_id(open_id)
            send_card_to_user(open_id, _welcome())
    except Exception as e:
        _log(f"发送欢迎卡片异常: {e}")


def _handle_message_read(_data) -> None:
    pass


# ── 帮助文本 ─────────────────────────────────────────────────

def _welcome() -> dict:
    return make_card("小助手", [
        {"text": "直接跟我说你想做什么就行。下面按功能列了常用说法，照着说即可："},
        {"divider": True},
        {"text": (
            "**1️⃣ 备忘**\n"
            "· 记一条：`备忘 下周交报告 #工作`（多条可换行或分号分隔）\n"
            "· 完成/删除：`完成 1`、`删掉 交报告`（按序号或内容都行）\n"
            "· 看列表：发 `线程` 看所有工作线，发 `看板` 导出到飞书表格"
        )},
        {"divider": True},
        {"text": (
            "**2️⃣ 项目 & 记账**\n"
            "· 建项目：`创建项目 Q2营销`（会引导设预算，统一管理在多维表格中）\n"
            "· 记一笔花费：`记账 午餐 35` 或 `记账 午餐 35 #Q2营销`\n"
            "· 看汇总：`本月花费`、`Q2营销 总览`"
        )},
        {"divider": True},
        {"text": (
            "**3️⃣ 联网研究**\n"
            "· 深度调研：`研究 XX 的增长策略`（多来源搜索 + 结构化报告）\n"
            "· 事实核查：`fact check 某条说法`"
        )},
        {"divider": True},
        {"text": (
            "**4️⃣ 日报·周报·月报**\n"
            "· 每天 08:00 自动发晨报、18:00 发收尾提醒\n"
            "· 发 `周报` 本周汇总、`月报` 全维度月度总结"
        )},
        {"divider": True},
        {"note": "发「帮助」可看完整指令列表 · 其他话我会当聊天回复"},
    ], color="turquoise")


def _help() -> dict:
    return help_card("小助手", [
        ("1️⃣ 备忘",
         "① 记一条：`备忘 内容 #标签`（标签可选，多条用换行或分号分隔）\n"
         "② 标记完成：`完成 1`、`做完了 交报告`、`第三条完成`\n"
         "③ 删除：`删除 1`、`删掉 交报告`（按序号或内容）\n"
         "④ 查看：`备忘列表` 看未完成，`线程` 看所有工作线"),
        ("2️⃣ 看板",
         "① `看板` — 导出所有线程到飞书表格\n"
         "② `看板 #标签` — 只导出指定线程\n"
         "③ 首次导出后，新备忘会自动追加；表格分区：今日新增 / 本周进行中 / 等待跟进 / 已完成"),
        ("3️⃣ 联网研究",
         "① `研究 xxx` — 多来源搜索、交叉验证、输出结构化报告\n"
         "② `fact check xxx` — 针对性事实核查"),
        ("4️⃣ 项目管理",
         "① `创建项目 名称` — 在项目管理中心多维表格中创建，并引导设预算\n"
         "② `名称 加任务 内容` — 写入任务表\n"
         "③ 发飞书妙记链接 → 自动归档到资料库；粘贴会议纪要 → AI 提取任务并导入\n"
         "④ `项目列表`、`名称 总览` — 查看项目"),
        ("5️⃣ 财务",
         "① 记一笔：`记账 描述 金额` 或 `记账 午餐 35 #Q2营销`（不带项目会提示选择）\n"
         "② 粘贴费用表格/清单 — AI 自动逐条识别\n"
         "③ `创建预算 名称` 设预算项；`本月花费` 月度汇总；`名称 预算` 预算执行对比\n"
         "④ `名称 设目标 xxx 数量 单位` 添加 KPI；`名称 总览` 预算+目标+花费全维度"),
        ("6️⃣ 日程 & 日报·周报·月报",
         "① 加日程：直接说 `明天下午3点开会`，自动加进飞书日历\n"
         "② 查日程：`今天`、`明天`\n"
         "③ 自动推送：每天 08:00 晨报、18:00 收尾提醒\n"
         "④ 手动报告：`周报` 本周汇总，`月报` 全维度月度总结"),
    ], footer="多步流程中发「取消」可退出 · 其他消息当聊天回复")


# ── 长连接 & 定时推送 ────────────────────────────────────────

RECONNECT_INITIAL_DELAY = 5
RECONNECT_MAX_DELAY = 300
RECONNECT_MULTIPLIER = 2


def _run_health_server(port: int) -> None:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        def log_message(self, *args):
            pass
    server = HTTPServer(("0.0.0.0", port), _Handler)
    _log(f"健康检查 HTTP 已监听 0.0.0.0:{port}")
    server.serve_forever()


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
    app_id = (os.environ.get("ASSISTANT_FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or "").strip()
    app_secret = (os.environ.get("ASSISTANT_FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "请设置环境变量 ASSISTANT_FEISHU_APP_ID / ASSISTANT_FEISHU_APP_SECRET\n"
            "（或复用 FEISHU_APP_ID / FEISHU_APP_SECRET）"
        )

    # TODO: 传递凭证应通过配置对象而非修改全局环境变量，同进程多机器人时会冲突
    os.environ["FEISHU_APP_ID"] = app_id
    os.environ["FEISHU_APP_SECRET"] = app_secret

    _log("备忘与日程助手启动")
    print("=" * 60)
    print("备忘与日程助手（长连接模式）")
    print()
    print("功能：记备忘、查日程、每日简报、AI 对话")
    print()
    print("断线后将自动重连，无需人工干预。")
    print("=" * 60)

    # 健康检查（PaaS 保活）
    port_str = (os.environ.get("PORT") or "").strip()
    if port_str:
        try:
            threading.Thread(target=_run_health_server, args=(int(port_str),), daemon=True).start()
        except ValueError:
            pass

    def _run_scheduler():
        try:
            from cal.daily_brief import run_daily_brief, run_weekly_report
        except Exception as e:
            _log(f"定时推送：导入失败: {e}")
            return
        try:
            import schedule as sched_lib
            sched_lib.every().day.at("08:00").do(lambda: run_daily_brief(is_morning=True))
            sched_lib.every().day.at("18:00").do(lambda: run_daily_brief(is_morning=False))
            sched_lib.every().monday.at("09:00").do(run_weekly_report)
            sched_lib.every().day.at("09:00").do(_run_reminder_check)
            while True:
                sched_lib.run_pending()
                time.sleep(60)
        except ImportError:
            _log("定时推送已禁用：未安装 schedule。pip install schedule")
        except Exception as e:
            _log(f"定时任务异常: {e}\n{traceback.format_exc()}")

    def _run_heartbeat():
        """大管家 heartbeat — 定期扫描事件轨迹，决定是否需要主动通知用户。"""
        _log("大管家 heartbeat 启动")
        _last_scan_ts = ""
        _HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL_SEC", "900"))

        while True:
            try:
                time.sleep(_HEARTBEAT_INTERVAL)
                from core.events import scan, scan_summary
                from cal.push_target import get_push_target_open_id

                open_id = get_push_target_open_id()
                if not open_id:
                    continue

                events = scan(hours=4, since_ts=_last_scan_ts)
                if not events:
                    continue

                _last_scan_ts = events[-1].get("ts", _last_scan_ts)

                alert_events = [e for e in events if e.get("event") == "alert"]
                if alert_events:
                    lines = ["⚡ **实时提醒**\n"]
                    for e in alert_events:
                        lines.append(f"- [{e.get('bot', '?')}] {e.get('summary', '')}")
                    try:
                        send_message_to_user(open_id, "\n".join(lines))
                        _log(f"heartbeat: 推送 {len(alert_events)} 条告警")
                    except Exception as e:
                        _log(f"heartbeat 推送告警失败: {e}")
                    continue

                significant = [e for e in events if e.get("event") in (
                    "session_completed", "planning_completed",
                    "pipeline_completed", "report_completed",
                    "digest_pushed",
                )]
                if len(significant) >= 3:
                    summary_text = scan_summary(hours=4)
                    try:
                        from core.llm import chat as llm_chat
                        decision = llm_chat(
                            f"你是团队的大管家助手。以下是过去几小时各 bot 的活动记录：\n{summary_text}\n\n"
                            "请判断是否需要通知用户。如果有值得汇报的进展（如脑暴完成、内容发布、舆情报告等），"
                            "用简洁的中文写一段 50 字以内的通知。如果没什么重要的，只回复「无」。",
                            system_prompt="你是一个判断是否需要打扰用户的 AI 助手。宁可漏报不可扰民。",
                        )
                        if decision and decision.strip() != "无":
                            send_message_to_user(open_id, f"📋 **大管家速报**\n\n{decision.strip()}")
                            _log(f"heartbeat: 推送速报 ({len(significant)} 个事件)")
                    except Exception as e:
                        _log(f"heartbeat LLM 决策失败: {e}")

            except Exception as e:
                _log(f"heartbeat 异常: {e}")
                time.sleep(60)

    def _run_reminder_check():
        """检查到期提醒并推送。"""
        try:
            from cal.push_target import get_push_target_open_id
            open_id = get_push_target_open_id()
            if not open_id:
                return
            reminders = get_due_reminders(user_open_id=open_id)
            if not reminders:
                return
            lines = ["⏰ 到期提醒：\n"]
            for r in reminders:
                thread = r.get("thread") or ""
                tag = f"[#{thread}] " if thread else ""
                lines.append(f"- {tag}{r.get('content', '')}")
                mark_reminder_sent(r.get("id", ""))
            send_message_to_user(open_id, "\n".join(lines))
            _log(f"已推送 {len(reminders)} 条到期提醒")
        except Exception as e:
            _log(f"提醒检查失败: {e}")

    try:
        import schedule as _s  # noqa: F401
        threading.Thread(target=_run_scheduler, daemon=True).start()
        _log("定时推送已启用：08:00 晨报 / 18:00 收尾 / 周一 09:00 周报 / 每日 09:00 提醒检查")
    except ImportError:
        _log("定时推送已跳过：未安装 schedule")

    threading.Thread(target=_run_heartbeat, daemon=True).start()
    _log(f"大管家 heartbeat 已启用（间隔 {os.environ.get('HEARTBEAT_INTERVAL_SEC', '900')} 秒）")

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
