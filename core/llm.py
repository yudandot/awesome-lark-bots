# -*- coding: utf-8 -*-
"""
LLM 调用统一封装层 —— 所有机器人调用大模型都经过这里。
=====================================

本项目同时使用三家大模型服务商，它们都兼容 OpenAI 的 API 协议：
  - DeepSeek ：主力模型，用于规划、助手、脑暴中的策略角色
  - 豆包(Doubao)：字节跳动的模型，用于脑暴中的创意角色
  - Kimi      ：月之暗面的模型，用于脑暴中的素材/体验角色

对外暴露两个函数：
  - chat_completion(): 完整调用，支持指定 provider、多轮对话、自动重试
  - chat()          : 快速调用 DeepSeek，适合意图解析、摘要等轻量场景

使用示例：
  >>> from core.llm import chat_completion, chat
  >>> # 完整调用
  >>> result = chat_completion(provider="deepseek", system="你是助手", user="你好")
  >>> # 快速调用
  >>> reply = chat("帮我总结一下今天的日程")
"""
import os
import time
from typing import Optional

from openai import OpenAI

# ── 客户端工厂 ──────────────────────────────────────────────
# 根据 provider 名称，从环境变量读取对应的 API 地址和密钥，
# 创建一个 OpenAI 兼容客户端。返回 (client, 默认模型名)。

def _get_client(provider: str):
    provider = (provider or "").strip().lower()
    timeout = float(os.environ.get("LLM_REQUEST_TIMEOUT", "120"))

    if provider == "deepseek":
        base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        return OpenAI(base_url=base.rstrip("/") + "/v1", api_key=key, timeout=timeout), model

    if provider in ("doubao", "豆包"):
        base = os.environ.get("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        key = os.environ.get("DOUBAO_API_KEY", "")
        model = os.environ.get("DOUBAO_MODEL", "") or "doubao-1.5-pro-32k"
        return OpenAI(base_url=base, api_key=key, timeout=timeout), model

    if provider == "kimi":
        base = os.environ.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
        key = os.environ.get("KIMI_API_KEY", "")
        model = os.environ.get("KIMI_MODEL", "moonshot-v1-128k")
        return OpenAI(base_url=base.rstrip("/"), api_key=key, timeout=timeout), model

    # 未匹配的 provider 一律走 DeepSeek
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    return OpenAI(base_url=base.rstrip("/") + "/v1", api_key=key, timeout=timeout), model


# ── 角色 → provider 映射 ────────────────────────────────────
# 脑暴机器人中，不同 AI 角色使用不同的大模型，以获得差异化的思维风格。
# 策略向角色用 DeepSeek（逻辑强），创意向用豆包（发散），素材向用 Kimi（长文本）。

ROLE_PROVIDER = {
    # legacy 八仙（旧版角色，已弃用但保留兼容）
    "Strategy Lead": "deepseek",
    "Audience Insight": "doubao",
    "Online Growth": "kimi",
    "Offline Experience": "kimi",
    "Brand Guardian": "doubao",
    "Conversion & Funnel": "deepseek",
    "Risk & Compliance": "deepseek",
    "Synthesizer": "deepseek",
    # 坚果五仁 v3（当前使用的角色）
    "芝麻仁": "deepseek",   # 现实架构师 → 逻辑型
    "核桃仁": "doubao",     # 玩家化身   → 创意型
    "杏仁": "kimi",         # 体验导演   → 素材型
    "瓜子仁": "kimi",       # 传播架构师 → 素材型
    "松子仁": "deepseek",   # 体验总成   → 逻辑型（负责最终收敛裁决）
}


def get_model_for_role(role_name: str) -> str:
    """根据角色名查找该角色应该使用哪个 LLM provider。找不到则默认 deepseek。"""
    return ROLE_PROVIDER.get(role_name, "deepseek")


# ── 多 provider 调用（带重试） ──────────────────────────────
# 调用大模型时可能遇到限流(429)或服务器错误(5xx)，
# 这里用「指数退避」策略自动重试：第1次等2秒，第2次等4秒，第3次等8秒。

MAX_RETRIES = 3      # 最多重试 3 次（加上首次 = 共 4 次尝试）
BASE_DELAY = 2.0     # 首次重试等待 2 秒


def chat_completion(
    *,
    provider: str,
    system: str = "",
    user: str = "",
    messages: Optional[list] = None,
    model_override: Optional[str] = None,
    temperature: float = 0.7,
) -> str:
    """
    调用 LLM 并返回文本结果。

    参数说明：
      provider      : 模型服务商，"deepseek" / "doubao" / "kimi"
      system        : 系统提示词（设定 AI 角色和行为规则）
      user          : 用户消息（你想让 AI 回答的内容）
      messages      : 多轮对话时直接传完整消息列表，此时 system/user 会被忽略
      model_override: 强制指定模型名，覆盖环境变量中的默认值
      temperature   : 创造力（0=确定性高, 1=更随机）

    自动处理：
      - 429 限流 / 5xx 服务器错误 → 指数退避重试，最多 3 次
      - 单次请求超时 120 秒（可通过 LLM_REQUEST_TIMEOUT 环境变量调整）
    """
    client, default_model = _get_client(provider)
    model = model_override or default_model
    if not model:
        raise ValueError(f"Missing model for provider: {provider}. Set env e.g. DEEPSEEK_MODEL.")

    # 如果没传 messages，就用 system + user 构建单轮对话
    if messages is None:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            last_error = e
            is_timeout = "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower()
            status = getattr(e, "status_code", None) or getattr(e, "code", None)
            # 只在可恢复的错误（限流/服务器错误/超时）时重试
            if attempt < MAX_RETRIES and (status in (429, 500, 502, 503) or is_timeout):
                time.sleep(BASE_DELAY * (2 ** attempt))  # 2s → 4s → 8s
                continue
            raise
    raise last_error  # type: ignore[misc]


# ── 简单调用（意图解析 / 日程汇总等轻量场景） ──────────────

def chat(user_message: str, system_prompt: Optional[str] = None) -> str:
    """
    快速调用 DeepSeek 的便捷函数。

    与 chat_completion() 的区别：
      - 固定使用 DeepSeek，无需指定 provider
      - temperature=0.3（更确定性的回答，适合解析/摘要）
      - 超时 30 秒，max_tokens 2048
      - 不带自动重试

    典型用途：意图解析、日程汇总、备忘分类等需要准确而非创意的场景。
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ValueError("请设置环境变量 DEEPSEEK_API_KEY")

    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "").strip() or "https://api.deepseek.com",
        timeout=30.0,
    )
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=os.environ.get("DEEPSEEK_MODEL", "").strip() or "deepseek-chat",
        messages=messages,
        max_tokens=2048,
        temperature=0.3,
    )
    if not response.choices or not response.choices[0].message.content:
        return ""
    return response.choices[0].message.content.strip()
