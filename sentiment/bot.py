# -*- coding: utf-8 -*-
"""
舆情监控机器人 —— 从社交媒体采集数据，生成分析材料。
===================================================

这是什么？
  在飞书上给这个机器人发消息，它可以从微博、抖音、小红书、B站等
  15 个平台采集社交媒体数据，生成结构化文件供 AI 深度分析。

三种使用方式：
  1. 快捷报告 ：发「周报」「月报」等一键生成预设报告
  2. 自定义采集：发「采集 关键词 @平台 天数」按需采集
  3. +分析    ：在指令末尾加「+分析」，同时用 AI 生成分析报告

数据流程：
  用户指令 → 解析关键词/平台/时间 → JustOneAPI 采集
  → 统计分析 → 导出 JSON + Markdown → (可选)上传 GitHub
  → (可选)AI 分析报告 → 结果回复用户

运行：python3 -m sentiment
环境变量：
  SENTIMENT_FEISHU_APP_ID   飞书应用凭证
  SENTIMENT_FEISHU_APP_SECRET
  JOA_TOKEN                 JustOneAPI 的 Token（数据采集必须）
  DEEPSEEK_API_KEY          AI 分析（可选）
  KIMI_API_KEY              Kimi 补充搜索（可选）
  GITHUB_TOKEN              GitHub 云存储（可选）
"""

import json
import os
import random
import re
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

from sentiment.feishu_api import reply_message, send_message_to_user, reply_card, send_card_to_user
from sentiment.runner import run_collect, format_result_message
from core.cards import welcome_card, progress_card, result_card, error_card, help_card, make_card, action_card
from sentiment.github_client import is_configured as github_configured
from sentiment.config.settings import (
    JOA_TOKEN, KIMI_API_KEY, DEEPSEEK_API_KEY,
    FEISHU_WEBHOOK_URL, JOA_BASE, ALL_PLATFORMS, PLATFORMS_DEFAULT, log,
)

# ── 日志 ─────────────────────────────────────────────────────

_log_lock = threading.Lock()
_bot_log_path: Optional[str] = None


def _log(msg: str) -> None:
    line = f"[SentimentBot] {msg}"
    print(line, file=sys.stderr, flush=True)
    global _bot_log_path
    with _log_lock:
        if _bot_log_path is None:
            _bot_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot_sentiment.log")
        try:
            with open(_bot_log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except Exception:
            pass


# ── 平台别名 ─────────────────────────────────────────────────
# 用户可以用各种方式指定平台（如 @B站、@bilibili、@b站 都指向 bilibili），
# 这里建立一个别名映射表，统一转换为内部 key。

_PLATFORM_ALIASES = {}
for _k, _cn in ALL_PLATFORMS.items():
    _PLATFORM_ALIASES[_k] = _k
    _PLATFORM_ALIASES[_cn] = _k
    _PLATFORM_ALIASES[_cn.lower()] = _k
_PLATFORM_ALIASES.update({
    "b站": "bilibili", "微信": "weixin", "公众号": "weixin",
    "头条": "toutiao", "今日头条": "toutiao",
    "红书": "xiaohongshu", "xhs": "xiaohongshu",
    "x": "twitter", "推特": "twitter",
    "ins": "instagram", "油管": "youtube",
    "天猫": "taobao", "pdd": "pinduoduo", "多多": "pinduoduo",
})

_COMMAND_MAP = {
    "周报": "brand-weekly", "/周报": "brand-weekly",
}
_BIWEEK_MAP = {
    "双周报": "sub-brand-biweek",
}

# ── 引导文案 ─────────────────────────────────────────────────

def _welcome() -> dict:
    return welcome_card(
        "舆情监控机器人",
        "我可以从 **微博、抖音、小红书、B站** 等 15 个平台采集社交媒体数据，"
        "生成可供 AI 深度分析的结构化文件。",
        examples=[
            "周报 — 一键生成舆情周报",
            "采集 我的品牌 @微博 @B站 7天 — 自定义采集",
            "平台 — 查看所有可用平台",
        ],
        hints=["加「+分析」可附 AI 分析报告", "发送「帮助」查看完整说明"],
    )


def _help() -> dict:
    return help_card("舆情机器人", [
        ("快捷报告（一键使用）",
         "> **周报** — 默认品牌舆情周报（7天）\n"
         "> **双周报** — 子品牌双周报（14天）"),
        ("自定义采集",
         "格式：`采集 关键词 @平台 天数 条数`\n\n"
         "> 采集 原神 崩坏星穹铁道 @微博 @B站 7天\n"
         "> 采集 iPhone17 @全平台 3天 200条\n"
         "> 我的品牌 @抖音 @小红书 14天 50条\n\n"
         "关键词空格分隔 · 不填平台默认国内6平台 · @全平台=15个"),
        ("可选项",
         "指令末尾加 **+分析** → 同时用 AI 生成分析报告\n"
         "例：`周报 +分析`"),
        ("其他指令",
         "> **平台** — 查看所有可用平台\n"
         "> **状态** — 查看配置状态"),
    ], footer="试试发送：周报")


def _unrecognized() -> dict:
    return action_card(
        "🤔 没有理解你的意思",
        "**试试这样说：**\n"
        "> 周报 — 生成舆情周报\n"
        "> 采集 我的品牌 @微博 @B站 7天 — 自定义采集\n"
        "> 帮助 — 查看完整说明",
        hints=["发「平台」查看可用平台列表"],
        color="orange",
    )


def _platforms_list() -> str:
    lines = ["📋 可用平台（共 15 个）", ""]
    lines.append("🇨🇳 国内社媒:")
    cn = ["weibo", "douyin", "xiaohongshu", "bilibili", "kuaishou", "zhihu", "toutiao", "weixin"]
    for k in cn:
        lines.append(f"  @{ALL_PLATFORMS[k]}")
    lines.append("")
    lines.append("🌍 海外社媒:")
    intl = ["tiktok", "youtube", "twitter", "instagram", "facebook"]
    for k in intl:
        lines.append(f"  @{ALL_PLATFORMS[k]}")
    lines.append("")
    lines.append("🛒 电商:")
    ec = ["taobao", "pinduoduo"]
    for k in ec:
        lines.append(f"  @{ALL_PLATFORMS[k]}")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━")
    lines.append("  @全平台 = 采集以上所有")
    lines.append("  不指定 = 默认国内6平台")
    lines.append("")
    lines.append("💡 试试: 采集 我的品牌 @微博 @抖音 @小红书 7天")
    return "\n".join(lines)


def _config_status() -> str:
    lines = [
        "🔧 配置状态",
        "",
        f"  数据采集 (JOA):   {'✅ 就绪' if JOA_TOKEN else '❌ 未设置 JOA_TOKEN'}",
        f"  AI 分析:          {'✅ DeepSeek' if DEEPSEEK_API_KEY else ''}{'+ Kimi' if KIMI_API_KEY else ''}"
        if (DEEPSEEK_API_KEY or KIMI_API_KEY) else f"  AI 分析:          ⚠️ 未设置（可选）",
        f"  云存储 (GitHub):  {'✅ 已配置' if github_configured() else '⚠️ 未配置'}",
        f"  飞书 Webhook:     {'✅ 已设置' if FEISHU_WEBHOOK_URL else '⚠️ 未设置'}",
    ]
    lines.append("")
    if JOA_TOKEN:
        lines.append("一切就绪！试试发送「周报」或「采集 关键词 @平台」")
    else:
        lines.append("⚠️ 需要先配置 JOA_TOKEN 才能采集数据")
    return "\n".join(lines)


# ── 指令解析 ─────────────────────────────────────────────────

def _parse_command(text: str):
    """
    解析用户输入的采集指令。

    返回 (command_type, params, with_ai)：
      command_type: 指令类型
        "preset"    → 预设快捷报告（如「周报」）
        "custom"    → 自定义采集（如「采集 我的品牌 @微博 7天」）
        "status"    → 查看配置状态
        "platforms" → 查看可用平台
        "help"      → 帮助
        None        → 无法识别
      params: 指令参数（dict）
      with_ai: 是否附带 AI 分析（用户末尾加了 +分析）
    """
    t = text.strip()
    with_ai = "+分析" in t
    if with_ai:
        t = t.replace("+分析", "").strip()

    lower = t.lower().strip()

    if lower in ("帮助", "help", "?", "？", "使用说明"):
        return "help", {}, False
    if lower in ("状态", "/状态", "config", "status", "配置"):
        return "status", {}, False
    if lower in ("平台", "/平台", "platforms", "平台列表"):
        return "platforms", {}, False

    if lower in _COMMAND_MAP:
        return "preset", {"profile_id": _COMMAND_MAP[lower]}, with_ai

    if lower.startswith(("双周报", "/双周报")):
        rest = lower.replace("/双周报", "").replace("双周报", "").strip()
        for key, pid in _BIWEEK_MAP.items():
            if key in rest:
                return "preset", {"profile_id": pid}, with_ai
        return "preset", {"profile_id": "sub-brand-biweek"}, with_ai

    has_collect_prefix = lower.startswith(("采集 ", "/采集 ", "采集:", "搜索 ", "/搜索 "))
    if has_collect_prefix:
        t = re.sub(r"^[/]?(采集|搜索)[:\s]+", "", t).strip()

    if not t:
        return None, {}, False

    tokens = t.split()
    keywords, platforms = [], []
    days = 7
    max_posts = None
    all_platforms = False
    has_structured_token = False

    for token in tokens:
        if token.startswith("@"):
            plat_name = token[1:]
            has_structured_token = True
            if plat_name in ("全平台", "all", "全部"):
                all_platforms = True
            else:
                plat_key = _PLATFORM_ALIASES.get(plat_name) or _PLATFORM_ALIASES.get(plat_name.lower())
                if plat_key:
                    platforms.append(plat_key)
                else:
                    keywords.append(token)
            continue
        m = re.match(r"^(\d+)[天日d]$", token)
        if m:
            days = int(m.group(1))
            has_structured_token = True
            continue
        m2 = re.match(r"^(\d+)条$", token)
        if m2:
            max_posts = int(m2.group(1))
            has_structured_token = True
            continue
        keywords.append(token)

    if not keywords:
        return None, {}, False

    if not has_collect_prefix and not has_structured_token:
        return None, {}, False

    if all_platforms:
        platforms = list(ALL_PLATFORMS.keys())
    elif not platforms:
        platforms = list(PLATFORMS_DEFAULT)

    return "custom", {
        "keywords": keywords,
        "platforms": platforms,
        "days": days,
        "max_posts": max_posts,
    }, with_ai


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


# ── 运行中追踪 ───────────────────────────────────────────────

_running_sessions: dict[str, str] = {}
_running_lock = threading.Lock()

# ── 消息处理 ─────────────────────────────────────────────────

def _handle_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    _log("收到消息事件")
    try:
        if not data.event or not data.event.message:
            return
        msg = data.event.message
        message_id = msg.message_id
        user_text = _extract_text(msg.content or "{}")
        open_id = None
        if data.event.sender and data.event.sender.sender_id:
            open_id = getattr(data.event.sender.sender_id, "open_id", None)
        _log(f"message_id={message_id!r} open_id={open_id!r} 文本={user_text[:80]!r}")
        if not user_text:
            threading.Thread(target=lambda: reply_card(message_id, _welcome()), daemon=True).start()
            return
    except Exception as e:
        _log(f"解析消息异常: {e}\n{traceback.format_exc()}")
        return

    def _reply(text_to_send: str):
        """优先主动发消息，回退到回复消息。"""
        if open_id:
            r = send_message_to_user(open_id, text_to_send)
        else:
            r = reply_message(message_id, text_to_send)
        code = r.get("code", -1)
        if code != 0:
            _log(f"发送失败 code={code} msg={r.get('msg')}")
        return r

    def _reply_c(card_data: dict):
        """优先主动发卡片，回退到回复卡片。"""
        if open_id:
            r = send_card_to_user(open_id, card_data)
        else:
            r = reply_card(message_id, card_data)
        code = r.get("code", -1)
        if code != 0:
            _log(f"发送卡片失败 code={code} msg={r.get('msg')}")
        return r

    def _process(mid: str, text: str, uid: Optional[str]):
        try:
            lower = text.strip().lower()
            if lower in ("hi", "hello", "你好", "嗨", "开始", "start"):
                _reply_c(_welcome())
                return

            cmd_type, params, with_ai = _parse_command(text)

            if cmd_type == "help":
                _reply_c(_help())
                return
            if cmd_type == "status":
                _reply_c(action_card("🔧 配置状态", _config_status(), color="blue"))
                return
            if cmd_type == "platforms":
                _reply_c(action_card("📋 可用平台", _platforms_list(), hints=["例：采集 我的品牌 @微博 @抖音 7天"], color="blue"))
                return
            if cmd_type is None:
                _reply_c(_unrecognized())
                return

            user_key = uid or mid
            with _running_lock:
                if user_key in _running_sessions:
                    _reply_c(progress_card(
                        "任务进行中",
                        f"当前任务：**{_running_sessions[user_key]}**\n\n请等它完成后再发起新的。",
                        color="orange",
                    ))
                    return
                if cmd_type == "preset":
                    _running_sessions[user_key] = params["profile_id"]
                elif cmd_type == "custom":
                    _running_sessions[user_key] = f"自定义: {', '.join(params['keywords'][:3])}"

            if cmd_type == "preset":
                profile_id = params["profile_id"]
                from sentiment.config.profiles import get_profile
                profile = get_profile(profile_id)
                ai_hint = " + AI分析" if with_ai else ""
                _reply_c(progress_card(
                    f"开始执行: {profile['title']}{ai_hint}",
                    f"**关键词：**{', '.join(profile['keywords'])}\n"
                    f"**时间：**过去 {profile['days']} 天\n"
                    f"**平台：**默认国内6平台\n\n"
                    f"采集通常需要 2-5 分钟...",
                ))
                _log(f"预设采集: profile={profile_id} with_ai={with_ai}")
                try:
                    result = run_collect(profile_id=profile_id, with_ai=with_ai)
                    _reply_c(result_card(
                        f"{profile['title']} 完成",
                        format_result_message(result),
                        next_actions=["再来一份报告", "加 +分析 看 AI 解读"],
                    ))
                finally:
                    with _running_lock:
                        _running_sessions.pop(user_key, None)

            elif cmd_type == "custom":
                keywords = params["keywords"]
                platforms = params["platforms"]
                days = params["days"]
                max_posts = params.get("max_posts")
                task_name = f"自定义: {', '.join(keywords[:3])}"
                plat_names = [ALL_PLATFORMS.get(p, p) for p in platforms]
                ai_hint = " + AI分析" if with_ai else ""
                limit_hint = f"\n**上限：**{max_posts} 条" if max_posts else ""
                _reply_c(progress_card(
                    f"开始自定义采集{ai_hint}",
                    f"**关键词：**{', '.join(keywords)}\n"
                    f"**平台：**{', '.join(plat_names)}\n"
                    f"**时间：**过去 {days} 天{limit_hint}",
                ))
                _log(f"自定义采集: keywords={keywords} platforms={platforms} days={days} max_posts={max_posts}")
                try:
                    result = run_collect(
                        profile_id="custom", with_ai=with_ai,
                        custom_keywords=keywords, custom_platforms=platforms,
                        custom_days=days, custom_max_posts=max_posts,
                    )
                    _reply_c(result_card(
                        "采集完成",
                        format_result_message(result),
                        next_actions=["换个关键词再采", "加 +分析 看 AI 解读"],
                    ))
                finally:
                    with _running_lock:
                        _running_sessions.pop(user_key, None)

        except Exception as e:
            _log(f"处理异常: {e}\n{traceback.format_exc()}")
            try:
                _reply_c(error_card("出错了", "内部错误，请稍后重试", suggestions=["重新发送试试", "发「帮助」查看说明"]))
            except Exception:
                pass

    threading.Thread(target=_process, args=(message_id, user_text, open_id), daemon=True).start()


def _handle_bot_p2p_chat_entered(data) -> None:
    """用户首次打开单聊时发送欢迎引导。"""
    _log("用户打开了与机器人的单聊")
    try:
        open_id = None
        if data.event and hasattr(data.event, "user_id"):
            open_id = data.event.user_id
        if not open_id and data.event and hasattr(data.event, "operator"):
            op = data.event.operator
            if op and hasattr(op, "open_id"):
                open_id = op.open_id
        if open_id:
            send_card_to_user(open_id, _welcome())
    except Exception as e:
        _log(f"欢迎消息发送失败: {e}")


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
    app_id = (os.environ.get("SENTIMENT_FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or "").strip()
    app_secret = (os.environ.get("SENTIMENT_FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise SystemExit("请设置环境变量 SENTIMENT_FEISHU_APP_ID 和 SENTIMENT_FEISHU_APP_SECRET")

    _log("舆情机器人启动")
    print("=" * 60)
    print("AIlarkteams 舆情监控机器人")
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
                print("  1. SENTIMENT_FEISHU_APP_ID / SECRET 是否正确", file=sys.stderr)
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
