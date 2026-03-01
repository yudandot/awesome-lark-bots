# -*- coding: utf-8 -*-
"""
早知天下事飞书机器人 — 定时推送 + 手动触发。

推送策略：
  日报会被拆分成多个逻辑段（华人圈/越南/亚太/欧美/全球联动），
  每段作为独立的飞书消息卡片发送，绕开单条消息的字数限制。
  每张卡片内部的 Markdown 也会按 element 上限自动拆分。

运行：python3 -m newsbot
"""

import json
import os
import random
import threading
import time
import traceback
from datetime import datetime
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests as _requests
import lark_oapi as lark
from lark_oapi import EventDispatcherHandler, LogLevel

from newsbot.config import (
    NEWSBOT_FEISHU_APP_ID, NEWSBOT_FEISHU_APP_SECRET,
    NEWSBOT_FEISHU_WEBHOOK, BEIJING, log,
)
from newsbot.run import generate_report

# ── 配置 ────────────────────────────────────────────────────

SCHEDULE_HOUR = int(os.getenv("NEWSBOT_SCHEDULE_HOUR", "8"))
SCHEDULE_MINUTE = int(os.getenv("NEWSBOT_SCHEDULE_MINUTE", "0"))
NEWSBOT_PUSH_OPEN_ID = os.getenv("NEWSBOT_PUSH_OPEN_ID", "").strip()

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
_token_cache: Optional[str] = None
_token_expire_at: float = 0.0

# 飞书卡片限制
MAX_CARD_ELEMENT_LEN = 3800          # 单个 markdown element 内容上限
MAX_CARD_ELEMENTS = 50               # 单张卡片最大 element 数
MAX_CARD_TOTAL_CHARS = 9000           # 单张卡片总字符安全上限（中文3字节/字 + JSON开销 ≈ 30KB）
CARD_SEND_INTERVAL = 1.5             # 多卡片之间发送间隔（秒）


# ── 飞书 API ────────────────────────────────────────────────

def _get_token() -> str:
    global _token_cache, _token_expire_at
    now = time.time()
    if _token_cache and _token_expire_at > now + 60:
        return _token_cache
    resp = _requests.post(
        f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": NEWSBOT_FEISHU_APP_ID, "app_secret": NEWSBOT_FEISHU_APP_SECRET},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 token 失败: {data}")
    _token_cache = data["tenant_access_token"]
    _token_expire_at = now + data.get("expire", 7200)
    return _token_cache


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}


def _reply_text(message_id: str, text: str) -> None:
    url = f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/reply"
    body = {"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)}
    try:
        r = _requests.post(url, json=body, headers=_headers(), timeout=10)
        d = r.json()
        if d.get("code") != 0:
            log.warning("回复失败: %s", d.get("msg"))
    except Exception as e:
        log.warning("回复异常: %s", e)


def _send_text(open_id: str, text: str) -> None:
    url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    try:
        r = _requests.post(url, json=body, headers=_headers(), timeout=10)
        d = r.json()
        if d.get("code") != 0:
            log.warning("发送失败: %s", d.get("msg"))
    except Exception as e:
        log.warning("发送异常: %s", e)


def _send_card_via_api(open_id: str, card: dict) -> bool:
    """通过飞书 API 发送消息卡片给指定用户。"""
    url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    try:
        r = _requests.post(url, json=body, headers=_headers(), timeout=15)
        d = r.json()
        if d.get("code") == 0:
            return True
        log.warning("API 卡片发送失败: %s", d.get("msg"))
    except Exception as e:
        log.warning("API 卡片发送异常: %s", e)
    return False


def _reply_card(message_id: str, card: dict) -> bool:
    """回复一张消息卡片。"""
    url = f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/reply"
    body = {
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    try:
        r = _requests.post(url, json=body, headers=_headers(), timeout=15)
        d = r.json()
        if d.get("code") == 0:
            return True
        log.warning("回复卡片失败: %s", d.get("msg"))
    except Exception as e:
        log.warning("回复卡片异常: %s", e)
    return False


# ── 卡片构建 ─────────────────────────────────────────────────

def _split_markdown_by_lines(text: str, max_len: int) -> list[str]:
    """按行边界拆分长文本，尽量在空行或标题处断开。"""
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_len and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))
    return chunks


def _build_card(title: str, markdown_body: str, color: str = "blue",
                subtitle: str = "") -> dict:
    """
    构建单张飞书消息卡片。
    自动将长 Markdown 拆分成多个 element。
    """
    elements: list[dict] = []

    if subtitle:
        elements.append({
            "tag": "markdown",
            "content": f"*{subtitle}*",
        })
        elements.append({"tag": "hr"})

    sections = markdown_body.split("\n---\n")
    for section in sections:
        section = section.strip()
        if not section:
            continue

        if len(section) <= MAX_CARD_ELEMENT_LEN:
            elements.append({"tag": "markdown", "content": section})
        else:
            chunks = _split_markdown_by_lines(section, MAX_CARD_ELEMENT_LEN)
            for chunk in chunks:
                elements.append({"tag": "markdown", "content": chunk})
        elements.append({"tag": "hr"})

    if elements and elements[-1].get("tag") == "hr":
        elements.pop()

    if not elements:
        elements = [{"tag": "markdown", "content": markdown_body[:MAX_CARD_ELEMENT_LEN]}]

    if len(elements) > MAX_CARD_ELEMENTS:
        elements = elements[:MAX_CARD_ELEMENTS]

    return {
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": elements,
    }


def _split_report_into_cards(report: str, date_str: str) -> list[dict]:
    """
    把完整日报拆分成多张卡片。
    按「## 」二级标题作为天然分割点，每张卡片一个大段。
    """
    import re
    # 按二级标题拆分
    parts = re.split(r'\n(?=## )', report)

    # 第一段是标题头（# 早知天下事...），单独处理
    header = ""
    body_parts: list[tuple[str, str]] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("# "):
            header = part
            continue

        title_match = re.match(r'^## (.+?)$', part, re.MULTILINE)
        section_title = title_match.group(1).strip() if title_match else "续"
        body_parts.append((section_title, part))

    cards: list[dict] = []
    base_title = f"📰 早知天下事 · {date_str}"

    SECTION_COLORS = {
        "华人圈": "blue",
        "越南": "green",
        "亚太": "orange",
        "欧美": "purple",
        "全球热点": "turquoise",
        "全球联动": "red",
    }

    if not body_parts:
        cards.append(_build_card(base_title, report, "blue"))
        return cards

    total = len(body_parts)
    for idx, (section_title, content) in enumerate(body_parts, 1):
        color = "blue"
        for keyword, c in SECTION_COLORS.items():
            if keyword in section_title:
                color = c
                break

        card_title = f"{base_title}  [{idx}/{total}]"
        subtitle = ""
        if idx == 1 and header:
            subtitle = header.replace("# ", "").strip()

        content_stripped = content.strip().removeprefix("---").strip()

        if len(content_stripped) > MAX_CARD_TOTAL_CHARS:
            sub_chunks = _split_markdown_by_lines(content_stripped, MAX_CARD_TOTAL_CHARS)
            for ci, chunk in enumerate(sub_chunks):
                sub_title = f"{base_title}  [{idx}.{ci+1}/{total}]"
                cards.append(_build_card(
                    sub_title, chunk, color,
                    subtitle=section_title if ci == 0 else f"{section_title}（续）",
                ))
        else:
            cards.append(_build_card(card_title, content_stripped, color, subtitle=section_title))

    return cards


# ── Webhook 推送 ─────────────────────────────────────────────

MAX_WEBHOOK_RETRIES = 2


def _webhook_send_card(card: dict, title_for_log: str = "") -> bool:
    """通过 Webhook 发送单张消息卡片。"""
    webhook_url = NEWSBOT_FEISHU_WEBHOOK
    if not webhook_url:
        return False

    body = {"msg_type": "interactive", "card": card}

    for attempt in range(MAX_WEBHOOK_RETRIES + 1):
        try:
            r = _requests.post(
                webhook_url, json=body,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            if r.ok:
                resp = r.json()
                if resp.get("code") == 0 or resp.get("StatusCode") == 0:
                    log.info("Webhook 卡片推送成功: %s", title_for_log)
                    return True
                log.warning("Webhook 返回异常: %s", resp)
            else:
                log.warning("Webhook HTTP %d: %s", r.status_code, r.text[:200])
            if attempt < MAX_WEBHOOK_RETRIES and r.status_code in (429, 500, 502, 503):
                time.sleep(2 * (attempt + 1))
                continue
            break
        except Exception as e:
            log.warning("Webhook 异常: %s", e)
            if attempt < MAX_WEBHOOK_RETRIES:
                time.sleep(2)
                continue
            break
    return False


def _webhook_send_text(text: str) -> bool:
    webhook_url = NEWSBOT_FEISHU_WEBHOOK
    if not webhook_url:
        return False
    body = {"msg_type": "text", "content": {"text": text}}
    try:
        r = _requests.post(webhook_url, json=body,
                           headers={"Content-Type": "application/json"}, timeout=10)
        return r.ok
    except Exception:
        return False


# ── 推送日报（核心逻辑） ──────────────────────────────────────

def push_report(report: str, date_str: str) -> None:
    """
    推送日报到所有配置的渠道。
    核心策略：按二级标题拆分为多张卡片，逐条发送。
    """
    cards = _split_report_into_cards(report, date_str)
    log.info("日报拆分为 %d 张卡片", len(cards))

    # Webhook 推群
    if NEWSBOT_FEISHU_WEBHOOK:
        for i, card in enumerate(cards, 1):
            title = card.get("header", {}).get("title", {}).get("content", f"卡片{i}")
            ok = _webhook_send_card(card, title_for_log=title)
            if not ok:
                # 降级：纯文本
                _webhook_send_text(f"⚠️ 卡片 {i}/{len(cards)} 发送失败，请查看文件版日报")
            if i < len(cards):
                time.sleep(CARD_SEND_INTERVAL)

    # API 推用户
    if NEWSBOT_PUSH_OPEN_ID:
        for i, card in enumerate(cards, 1):
            ok = _send_card_via_api(NEWSBOT_PUSH_OPEN_ID, card)
            if not ok:
                preview = report[:3000] if i == 1 else f"（第{i}段发送失败）"
                _send_text(NEWSBOT_PUSH_OPEN_ID, preview)
            if i < len(cards):
                time.sleep(CARD_SEND_INTERVAL)


def push_cards_to_chat(message_id: str, open_id: Optional[str],
                       report: str, date_str: str) -> None:
    """
    在聊天中推送日报卡片（手动触发时使用）。
    第一张卡片用 reply，后续用 send。
    """
    cards = _split_report_into_cards(report, date_str)
    log.info("聊天回复: 日报拆分为 %d 张卡片", len(cards))

    for i, card in enumerate(cards, 1):
        if i == 1:
            ok = _reply_card(message_id, card)
        elif open_id:
            ok = _send_card_via_api(open_id, card)
        else:
            ok = False

        if not ok:
            fallback = f"⚠️ 第 {i}/{len(cards)} 段发送失败"
            if open_id:
                _send_text(open_id, fallback)
            else:
                _reply_text(message_id, fallback)

        if i < len(cards):
            time.sleep(CARD_SEND_INTERVAL)


# ── 定时调度 ────────────────────────────────────────────────

_schedule_running = False


def _daily_job():
    log.info("=" * 60)
    log.info("定时任务启动: 早知天下事日报")
    log.info("=" * 60)
    try:
        report, path = generate_report(regions=None, with_ai=True)
        now = datetime.now(BEIJING)
        date_str = now.strftime("%Y年%m月%d日")
        push_report(report, date_str)
        log.info("定时推送完成: %s (%d 字)", path.name, len(report))
    except Exception as e:
        log.error("定时任务失败: %s\n%s", e, traceback.format_exc())
        if NEWSBOT_FEISHU_WEBHOOK:
            _webhook_send_text(f"❌ 早知天下事日报生成失败\n\n{str(e)[:500]}")


def _scheduler_loop():
    global _schedule_running
    _schedule_running = True
    last_run_date: Optional[str] = None

    log.info("定时调度已启动: 每天 %02d:%02d (北京时间) 自动生成日报",
             SCHEDULE_HOUR, SCHEDULE_MINUTE)

    while _schedule_running:
        try:
            now = datetime.now(BEIJING)
            today_str = now.strftime("%Y-%m-%d")
            if (now.hour == SCHEDULE_HOUR
                    and now.minute == SCHEDULE_MINUTE
                    and today_str != last_run_date):
                last_run_date = today_str
                log.info("到达推送时间 %02d:%02d，启动日报生成...",
                         SCHEDULE_HOUR, SCHEDULE_MINUTE)
                threading.Thread(target=_daily_job, daemon=True,
                                 name="daily-digest").start()
        except Exception as e:
            log.error("调度器异常: %s", e)
        time.sleep(30)


def start_scheduler():
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler")
    t.start()
    return t


# ── 消息处理 ────────────────────────────────────────────────

WELCOME_TEXT = """👋 你好！我是「早知天下事」全球热点日报机器人。

📊 覆盖 20+ 数据源：
  🇨🇳 微博·百度·知乎·B站·抖音·头条·微信·澎湃
  🇹🇼🇭🇰 PTT·LIHKG·Google News 台湾/香港
  🌐 Reddit·Hacker News·Google News
  🇻🇳🇯🇵🇰🇷🇮🇳🇮🇩 VnExpress·NHK·Yonhap·TOI 等
  🇺🇸🇬🇧🇩🇪🇫🇷 CNN·BBC·Guardian·Spiegel 等

📋 指令：
  「日报」— 完整AI深度分析日报（~5分钟）
  「快报」— 只采集原始热榜（~1分钟）
  「华人圈」/「国际」— 分区域生成
  「帮助」— 详细说明

⏰ 每天 8:00 自动推送"""

HELP_TEXT = """📖 早知天下事 — 使用说明

━━━ 指令 ━━━
  日报 / 今日热点 / 新闻    完整 AI 深度分析日报（~5分钟）
  快报                      只采集原始热榜（~1分钟）
  华人圈                    只生成华人圈部分
  国际                      只生成国际部分
  帮助 / help               查看本说明

━━━ 20+ 数据源 ━━━
  中国大陆  微博·百度·知乎·B站·抖音·今日头条·微信热文·澎湃
  台湾/香港  PTT·LIHKG·Google News 台湾/香港
  全球社区  Reddit·Hacker News·Google News Global
  越南      VnExpress·Tuổi Trẻ·Dân Trí
  日韩      NHK·Japan Times·Mainichi·Yonhap
  印度      TOI·NDTV
  印尼      Google News Indonesia
  欧美      CNN·NPR·BBC·Guardian·Spiegel·Zeit·Le Monde·Le Figaro

━━━ AI 分析维度 ━━━
  • 跨平台叙事差异比较
  • 四地（内地/台湾/香港/海外）舆论温度计
  • 信息盲区与异常信号检测
  • 全球联动分析 & 信息差地图
  • 48小时风向预判

⏰ 每天 8:00（北京时间）自动推送"""

_running_lock = threading.Lock()
_running_users: dict = {}


def _parse_command(text: str):
    t = text.strip().lower()
    if t in ("帮助", "help", "?", "？"):
        return "help", {}
    if t in ("hi", "hello", "你好", "开始", "start", ""):
        return "welcome", {}
    if t in ("日报", "今日热点", "新闻", "热点", "生成日报", "/日报"):
        return "full", {"regions": None, "with_ai": True}
    if t in ("快报", "原始数据", "/快报"):
        return "full", {"regions": None, "with_ai": False}
    if t in ("华人圈", "中国", "国内", "/华人圈"):
        return "full", {"regions": ["cn"], "with_ai": True}
    if t in ("国际", "海外", "世界", "/国际"):
        return "full", {"regions": ["vn", "asia", "west"], "with_ai": True}
    return None, {}


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


def _handle_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    log.info("收到消息事件")
    try:
        if not data.event or not data.event.message:
            return
        msg = data.event.message
        message_id = msg.message_id
        user_text = _extract_text(msg.content or "{}")
        open_id = None
        if data.event.sender and data.event.sender.sender_id:
            open_id = getattr(data.event.sender.sender_id, "open_id", None)
    except Exception as e:
        log.error("解析消息异常: %s", e)
        return

    def _respond(text_to_send: str):
        if open_id:
            _send_text(open_id, text_to_send)
        else:
            _reply_text(message_id, text_to_send)

    def _process():
        try:
            cmd, params = _parse_command(user_text)

            if cmd == "help":
                _respond(HELP_TEXT)
                return
            if cmd == "welcome" or cmd is None:
                _respond(WELCOME_TEXT)
                return

            user_key = open_id or message_id
            with _running_lock:
                if user_key in _running_users:
                    _respond(f"⏳ 正在生成中（{_running_users[user_key]}），请等待完成。")
                    return
                _running_users[user_key] = "日报生成中"

            try:
                regions = params.get("regions")
                with_ai = params.get("with_ai", True)
                ai_hint = "" if with_ai else "（快报模式，不含 AI 分析）"
                region_hint = "完整版" if not regions else "/".join(regions)

                _respond(
                    f"🚀 开始生成 {region_hint} 热点日报{ai_hint}\n\n"
                    f"⏳ 预计 {'3-5 分钟' if with_ai else '1 分钟'}，"
                    f"完成后以卡片形式分段发送。"
                )

                report, path = generate_report(regions=regions, with_ai=with_ai)
                now = datetime.now(BEIJING)
                date_str = now.strftime("%Y年%m月%d日")

                push_cards_to_chat(message_id, open_id, report, date_str)

                _respond(
                    f"✅ 日报已完成！\n"
                    f"📄 文件: {path.name}\n"
                    f"📊 共 {len(report)} 字"
                )
            finally:
                with _running_lock:
                    _running_users.pop(user_key, None)

        except Exception as e:
            log.error("处理异常: %s\n%s", e, traceback.format_exc())
            try:
                _respond(f"❌ 生成失败: {str(e)[:200]}\n\n发送「帮助」查看说明")
            except Exception:
                pass

    threading.Thread(target=_process, daemon=True).start()


def _handle_chat_entered(data) -> None:
    try:
        open_id = None
        if data.event and hasattr(data.event, "operator"):
            op = data.event.operator
            if op and hasattr(op, "open_id"):
                open_id = op.open_id
        if open_id:
            _send_text(open_id, WELCOME_TEXT)
    except Exception as e:
        log.warning("欢迎消息发送失败: %s", e)


# ── 启动 ────────────────────────────────────────────────────

RECONNECT_INITIAL_DELAY = 5
RECONNECT_MAX_DELAY = 300


def main():
    app_id = NEWSBOT_FEISHU_APP_ID.strip()
    app_secret = NEWSBOT_FEISHU_APP_SECRET.strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "请设置环境变量 NEWSBOT_FEISHU_APP_ID 和 NEWSBOT_FEISHU_APP_SECRET"
        )

    print("=" * 60)
    print("  早知天下事 — 全球热点日报机器人")
    print("=" * 60)
    print(f"  飞书应用: {app_id}")
    print(f"  Webhook:  {'✅ 已配置' if NEWSBOT_FEISHU_WEBHOOK else '❌ 未配置'}")
    print(f"  定时推送: 每天 {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} (北京时间)")
    print(f"  推送用户: {NEWSBOT_PUSH_OPEN_ID or '未配置（通过 Webhook 推群）'}")
    print("=" * 60)

    start_scheduler()

    delay = RECONNECT_INITIAL_DELAY
    attempt = 0
    while True:
        attempt += 1
        log.info("连接飞书… (第 %d 次)", attempt)
        try:
            event_handler = (
                EventDispatcherHandler.builder("", "")
                .register_p2_im_message_receive_v1(_handle_message)
                .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(_handle_chat_entered)
                .build()
            )
            cli = lark.ws.Client(
                app_id, app_secret,
                event_handler=event_handler,
                log_level=LogLevel.DEBUG,
                domain="https://open.feishu.cn",
            )
            delay = RECONNECT_INITIAL_DELAY
            cli.start()
        except Exception as e:
            log.error("连接失败: %s", e)
        wait = min(delay, RECONNECT_MAX_DELAY) + random.uniform(0, 3)
        log.info("%.1fs 后重连…", wait)
        time.sleep(wait)
        delay = min(delay * 2, RECONNECT_MAX_DELAY)


if __name__ == "__main__":
    main()
