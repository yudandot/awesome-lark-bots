# -*- coding: utf-8 -*-
"""
舆情机器人专用的飞书 API 客户端。

使用 SENTIMENT_FEISHU_APP_ID / SECRET 获取独立的 tenant_access_token，
避免与主项目的其他机器人凭证冲突。
"""

import json
import os
import sys
import time
from typing import Optional

import requests

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"

_token_cache: Optional[str] = None
_token_expire_at: float = 0.0


def _warn(msg: str) -> None:
    print(f"[Sentiment Feishu] {msg}", file=sys.stderr, flush=True)


def _get_credentials():
    """与 sentiment/bot.py main() 一致：优先 SENTIMENT_*，未配则回退到 FEISHU_APP_ID/SECRET。"""
    app_id = (os.environ.get("SENTIMENT_FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or "").strip()
    app_secret = (os.environ.get("SENTIMENT_FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise ValueError("请设置环境变量 SENTIMENT_FEISHU_APP_ID 和 SENTIMENT_FEISHU_APP_SECRET（或 FEISHU_APP_ID / FEISHU_APP_SECRET）")
    return app_id, app_secret


def get_tenant_access_token() -> str:
    global _token_cache, _token_expire_at
    now = time.time()
    if _token_cache and _token_expire_at > now + 60:
        return _token_cache
    app_id, app_secret = _get_credentials()
    url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 sentiment tenant_access_token 失败: {data}")
    _token_cache = data["tenant_access_token"]
    _token_expire_at = now + data.get("expire", 7200)
    return _token_cache


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_tenant_access_token()}", "Content-Type": "application/json"}


def reply_message(message_id: str, text: str) -> dict:
    url = f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/reply"
    payload = {"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)}
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            _warn(f"回复消息失败 code={data.get('code')} msg={data.get('msg')}")
        return data
    except Exception as e:
        _warn(f"回复消息异常: {e}")
        return {"code": -1, "msg": str(e)}


def send_message_to_user(open_id: str, text: str) -> dict:
    url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id"
    payload = {
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            _warn(f"主动发消息失败 code={data.get('code')} msg={data.get('msg')}")
        return data
    except Exception as e:
        _warn(f"主动发消息异常: {e}")
        return {"code": -1, "msg": str(e)}


def reply_card(message_id: str, card: dict) -> dict:
    url = f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/reply"
    payload = {"msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)}
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            _warn(f"回复卡片失败 code={data.get('code')} msg={data.get('msg')}")
        return data
    except Exception as e:
        _warn(f"回复卡片异常: {e}")
        return {"code": -1, "msg": str(e)}


def send_card_to_user(open_id: str, card: dict) -> dict:
    url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id"
    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            _warn(f"主动发卡片失败 code={data.get('code')} msg={data.get('msg')}")
        return data
    except Exception as e:
        _warn(f"主动发卡片异常: {e}")
        return {"code": -1, "msg": str(e)}
