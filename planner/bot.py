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

from core.feishu_client import reply_message, reply_card, send_message_to_user, send_card_to_user
from core.cards import welcome_card, progress_card, result_card, error_card, help_card
from planner.run import run_planning, detect_mode

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

def _welcome() -> dict:
    return welcome_card(
        "规划机器人",
        "告诉我你想规划什么，我会用 **理性六步法** 帮你从问题定义到执行方案一步步拆解。",
        examples=[
            "设计一个 AI agent 系统来自动化日常工作",
            "规划：Q3 用户增长策略",
            "快速模式：下周产品发布计划",
        ],
        hints=["消息前加「快速模式：」可切换模式", "发送「帮助」查看所有模式"],
    )


def _help() -> dict:
    return help_card("规划机器人", [
        ("使用方式", "直接发消息即为规划主题，可加「规划：」前缀。"),
        ("五种模式",
         "**完整规划**（默认）问题定义 → 现状分析 → 方案生成 → 评估矩阵 → 执行计划 → 反馈机制\n"
         "**快速模式** 跳过现状分析和反馈机制，更快出结果\n"
         "**分析模式** 仅做问题定义 + 现状分析\n"
         "**方案模式** 仅生成 3 个战略方案\n"
         "**执行模式** 仅生成执行计划"),
        ("切换模式", "在消息前加模式名即可：\n> 快速模式：下周产品发布计划\n> 分析模式：竞品定价策略"),
        ("多行消息", "第一行 = 主题\n其余行 = 背景材料"),
    ], footer="规划过程约 2-4 分钟，实时推送到飞书群")


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


# ── 运行中追踪 ───────────────────────────────────────────────

_running_sessions: dict[str, str] = {}
_running_lock = threading.Lock()


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
            topic, context, mode = _parse_planning_input(text)
            if not topic:
                reply_card(mid, _welcome())
                return
            user_key = uid or mid
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
                path = run_planning(topic=topic, context=context, mode=mode)
                done_card = result_card(
                    "规划完成",
                    fields=[("主题", topic[:100]), ("模式", mode), ("会话文件", f"`{path}`")],
                    next_actions=["发新主题继续规划", "换个模式试试", "去飞书群看完整过程"],
                )
                if uid:
                    send_card_to_user(uid, done_card)
                else:
                    reply_card(mid, done_card)
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
    # SECURITY TODO: 配置飞书事件订阅的 Verification Token 和 Encrypt Key 以启用签名校验
    # 当前为空字符串，不校验事件来源，生产环境建议配置
    event_handler = (
        EventDispatcherHandler.builder("", "")
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
