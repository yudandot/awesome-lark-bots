# -*- coding: utf-8 -*-
"""
脑暴机器人 —— 飞书长连接入口。
==============================

这是什么？
  在飞书上给这个机器人发消息，就能启动一场 AI 多角色脑暴。
  5 个 AI 角色（坚果五仁团队）会像真人一样轮流发言讨论你的主题，
  讨论过程实时推送到飞书群，最终产出可落地的创意方案。

运行方式：
  python3 -m brainstorm

需要的环境变量：
  BRAINSTORM_FEISHU_APP_ID / BRAINSTORM_FEISHU_APP_SECRET（推荐，避免与指挥等共用 .env 时用错）
  或 FEISHU_APP_ID / FEISHU_APP_SECRET  飞书应用的 App ID / Secret
  DEEPSEEK_API_KEY   DeepSeek 的 API Key（必须）
  DOUBAO_API_KEY     豆包的 API Key（脑暴必须）
  KIMI_API_KEY       Kimi 的 API Key（脑暴必须）
  FEISHU_WEBHOOK     飞书群 Webhook URL（讨论过程推送到群）

消息格式：
  直接发消息内容即为脑暴主题，例如：
    咖啡品牌 × 音乐节跨界联动
  或带前缀：
    脑暴：给男人卖胸罩
  多行消息第一行为主题，其余为背景材料。
  发送「帮助」查看使用说明。

整体流程（小白版）：
  用户发消息 → 解析主题 → DeepSeek 优化主题 → 5个角色4轮讨论
  → 每轮实时推送飞书群 → Kimi 生成最终交付 → 通知用户完成
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
from brainstorm.run import run_brainstorm
from core.utils import load_context

# ── 日志 ─────────────────────────────────────────────────────

_log_lock = threading.Lock()
_bot_log_path: Optional[str] = None


def _log(msg: str) -> None:
    line = f"[BrainstormBot] {msg}"
    print(line, file=sys.stderr, flush=True)
    global _bot_log_path
    with _log_lock:
        if _bot_log_path is None:
            _bot_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot_brainstorm.log")
        try:
            with open(_bot_log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except Exception:
            pass


# ── 消息解析 ─────────────────────────────────────────────────
# 用户发来的消息可能带有「脑暴：」等前缀，需要去掉前缀提取真正的主题。

_TOPIC_PREFIXES = ("脑暴 ", "脑暴：", "脑暴:", "brainstorm ", "brainstorm:", "brainstorm：")

def _welcome() -> dict:
    return welcome_card(
        "脑暴机器人",
        "**使用方式：**直接发消息，内容即为脑暴主题。可加「脑暴：」前缀，也可以不加。\n\n"
        "**脑暴流程：**\n"
        "1️⃣ DeepSeek 优化主题\n"
        "2️⃣ 坚果五仁团队四轮讨论（实时推送飞书群）\n"
        "3️⃣ 最终交付（总结 + Claude Code prompt + 视觉 prompt）",
        examples=[
            "咖啡品牌 × 音乐节跨界联动",
            "脑暴：博物馆夜间沉浸式体验",
            "宠物友好社区活动策划",
        ],
        hints=["多行消息：第一行为主题，其余为背景材料", "发送「帮助」查看完整说明"],
    )


def _help() -> dict:
    return help_card("脑暴机器人", [
        ("使用方式", "直接发消息，内容即为脑暴主题。\n可加「脑暴：」前缀，也可以不加。"),
        ("多行消息", "第一行 = 主题\n其余行 = 背景材料"),
        ("脑暴流程",
         "1️⃣ DeepSeek 优化主题\n"
         "2️⃣ 坚果五仁团队四轮讨论（实时推送飞书群）\n"
         "3️⃣ 最终交付（总结 + Claude Code prompt + 视觉 prompt）"),
        ("示例",
         "> 咖啡品牌 × 音乐节跨界联动\n"
         "> 脑暴：博物馆夜间沉浸式体验\n"
         "> 宠物友好社区活动策划"),
    ], footer="脑暴过程约 3-5 分钟，完成后会通知你")


def _extract_text(content: str) -> str:
    """从飞书消息体中提取纯文本。飞书传来的 content 是 JSON 字符串，如 '{"text":"你好"}'。"""
    if not content or not content.strip():
        return ""
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "text" in data:
            return (data["text"] or "").strip()
        return content.strip()
    except (json.JSONDecodeError, TypeError):
        return content.strip()


def _parse_brainstorm_input(text: str) -> tuple[str, str]:
    """
    从用户消息中解析出 (主题, 背景材料)。

    规则：第一行为主题，后续行为背景材料。
    支持去掉「脑暴：」等前缀。
    """
    t = (text or "").strip()
    for prefix in _TOPIC_PREFIXES:
        if t.lower().startswith(prefix):
            t = t[len(prefix):].strip()
            break
    lines = t.split("\n", 1)
    topic = lines[0].strip()
    context = lines[1].strip() if len(lines) > 1 else ""
    if context.startswith("---"):
        context = context[3:].strip()
    return topic, context


# ── 运行中追踪 ───────────────────────────────────────────────
# 记录每个用户正在进行的脑暴会话，防止同一用户同时发起多场脑暴。
# key = 用户 open_id, value = 当前脑暴的主题。

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
            topic, context = _parse_brainstorm_input(text)
            if not topic:
                reply_card(mid, _welcome())
                return
            user_key = uid or mid
            with _running_lock:
                if user_key in _running_sessions:
                    reply_card(mid, progress_card(
                        "脑暴进行中",
                        f"当前主题：**{_running_sessions[user_key][:40]}**\n\n请等当前脑暴结束后再发起新的。",
                        color="orange",
                    ))
                    return
                _running_sessions[user_key] = topic
            reply_card(mid, progress_card(
                "正在启动脑暴",
                f"**主题：**{topic[:200]}\n\n讨论过程将实时推送到飞书群，完成后我会通知你。",
            ))
            _log(f"启动脑暴: topic={topic[:80]!r}")
            try:
                path = run_brainstorm(topic=topic, context=context)
                done_card = result_card(
                    "脑暴完成",
                    fields=[("主题", topic[:100]), ("会话文件", f"`{path}`")],
                    next_actions=["发新主题再来一轮", "去飞书群看完整讨论"],
                )
                if uid:
                    send_card_to_user(uid, done_card)
                else:
                    reply_card(mid, done_card)
                _log(f"脑暴完成: {path}")
            except Exception as e:
                _log(f"脑暴异常: {e}\n{traceback.format_exc()}")
                err = error_card("脑暴执行出错", "内部错误，请稍后重试", suggestions=["重新发送主题再试一次"])
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
            ev = data.event
            for attr in ("operator_id", "operator", "user_id"):
                obj = getattr(ev, attr, None)
                if obj:
                    open_id = getattr(obj, "open_id", None)
                    if open_id:
                        break
        if open_id:
            send_card_to_user(open_id, _welcome())
        else:
            _log("无法获取 open_id，跳过欢迎卡片")
    except Exception as e:
        _log(f"发送欢迎卡片异常: {e}\n{traceback.format_exc()}")


def _handle_message_read(_data) -> None:
    pass


# ── 长连接 ───────────────────────────────────────────────────
# 飞书长连接（WebSocket）会保持和飞书服务器的持久连接，实时接收消息。
# 如果连接断开（网络波动等），会自动重连，重连间隔从 5 秒开始指数增长，
# 最长 300 秒（5分钟）。加入随机抖动(jitter)避免多个实例同时重连。

RECONNECT_INITIAL_DELAY = 5       # 首次重连等待 5 秒
RECONNECT_MAX_DELAY = 300         # 最长等待 300 秒
RECONNECT_MULTIPLIER = 2          # 每次翻倍


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
    # 优先用脑暴专用变量，避免与指挥/其他 bot 共用 FEISHU_APP_ID 时用错 token、发错欢迎卡片
    app_id = (
        os.environ.get("BRAINSTORM_FEISHU_APP_ID")
        or os.environ.get("FEISHU_APP_ID")
        or ""
    ).strip()
    app_secret = (
        os.environ.get("BRAINSTORM_FEISHU_APP_SECRET")
        or os.environ.get("FEISHU_APP_SECRET")
        or ""
    ).strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "请设置环境变量 BRAINSTORM_FEISHU_APP_ID / BRAINSTORM_FEISHU_APP_SECRET（或 FEISHU_APP_ID / FEISHU_APP_SECRET）"
        )
    # 让 core.feishu_client 的 get_tenant_access_token 使用脑暴的凭证发消息/卡片
    os.environ["FEISHU_APP_ID"] = app_id
    os.environ["FEISHU_APP_SECRET"] = app_secret

    _log("脑暴机器人启动")
    print("=" * 60)
    print("AIlarkteams 脑暴机器人（长连接模式）")
    print()
    print("使用方式：在飞书上给机器人发消息，内容即为脑暴主题。")
    print()
    print("飞书开放平台配置：")
    print("  1. 先保持本程序运行")
    print("  2. 事件订阅 → 选择「长连接」")
    print("  3. 订阅「接收消息 v2.0」(im.message.receive_v1)")
    print("  4. 保存")
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
                print("\n若持续失败，请检查：", file=sys.stderr)
                print("  1. BRAINSTORM_FEISHU_APP_ID / BRAINSTORM_FEISHU_APP_SECRET（或 FEISHU_APP_ID / SECRET）是否正确", file=sys.stderr)
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
