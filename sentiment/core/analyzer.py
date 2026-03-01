# -*- coding: utf-8 -*-
"""
AI 分析模块 — Kimi / DeepSeek 报告生成 & 联网搜索补充。
此模块为可选功能，用户可选择仅采集数据不进行 AI 分析。
"""

import requests
from sentiment.config.settings import (
    KIMI_API_KEY, DEEPSEEK_API_KEY, KIMI_REPORT_MAX_TOKENS,
    KIMI_REPORT_WEB_SEARCH, MAX_POSTS_BLOCK_CHARS, log,
)
from sentiment.core.stats import stats_text


# ---------------------------------------------------------------------------
# Prompt 构建
# ---------------------------------------------------------------------------

def _build_kimi_prompt(posts: list[dict], stats: dict, profile: dict,
                       web_supplement: str = "") -> str:
    subject = profile.get("subject", "品牌")
    days = profile.get("days", 7)
    period_text = "过去7天" if days == 7 else f"过去{days}天"

    plat_counts = stats["platform"]
    sample = list(posts)
    lines = []
    n_shown = 0
    for p in sample:
        line = f"[{p['platform']}] {p['title']} — {p['content'][:200]}"
        if len("\n".join(lines)) + len(line) + 1 > MAX_POSTS_BLOCK_CHARS:
            break
        lines.append(line)
        n_shown += 1
    posts_block = "\n".join(lines)
    if n_shown < len(sample):
        posts_block += (f"\n\n（因单次请求长度限制，以上仅展示前 {n_shown} 条，"
                        f"全量共 {len(sample)} 条；【统计参考】基于全量 {len(sample)} 条。）")
        log.info("Kimi 全量样本截断展示: 前 %d 条 / 全量 %d 条", n_shown, len(sample))
    else:
        log.info("Kimi 使用全量样本: %d 条，各平台: %s", len(sample),
                 {p: len([x for x in sample if x["platform"] == p]) for p in plat_counts})
    stats_block = stats_text(stats)
    web_block = ""
    if web_supplement and len(web_supplement.strip()) > 0:
        web_block = f"""
【Kimi 联网补充】（与本次采集并行执行，供交叉印证；请结合下方样本与统计综合判断）
{web_supplement.strip()[:12000]}
【联网补充结束】
"""
    return f"""你是一名资深游戏舆情与社区生态分析师。请参考{subject}中国大陆社交媒体舆情报告的标准格式，基于下方样本与统计（及可选联网补充），输出一份结构完整、有干货、可供决策使用的报告。

重要原则：不编造数据；不虚构版本或活动；不使用营销语气；风险判断克制；普通吐槽不等于风险；区分「负面情绪」与「真实舆情风险」。

以下为{period_text}社媒样本数据（已去重）：

【数据开始】
{posts_block}
【数据结束】

【统计参考】
{stats_block}
{web_block}

请输出一份结构完整的舆情报告（执行摘要→数据说明→舆情主题 Top 7→平台分层→情绪与诉求→玩家画像→风险与机会清单→附录关键词），全文不少于一万字。"""


# ---------------------------------------------------------------------------
# DeepSeek 备用
# ---------------------------------------------------------------------------

def _analyze_with_deepseek(system_content: str, user_prompt: str) -> str:
    if not DEEPSEEK_API_KEY:
        return ""
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": min(KIMI_REPORT_MAX_TOKENS, 8192),
    }
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=600,
        )
        if resp.status_code != 200:
            try:
                err = resp.json()
                log.warning("DeepSeek API %s: %s", resp.status_code, err)
            except Exception:
                log.warning("DeepSeek API %s: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        data = resp.json()
        msg = data.get("choices", [{}])[0].get("message", {})
        return (msg.get("content") or "").strip()
    except Exception as e:
        log.warning("DeepSeek API fallback failed: %s", e)
        return ""


# ---------------------------------------------------------------------------
# 主分析入口
# ---------------------------------------------------------------------------

def analyze_with_ai(posts: list[dict], stats: dict, profile: dict,
                    web_supplement: str = "") -> str:
    """优先 DeepSeek；若失败且已配置 KIMI_API_KEY 则改用 Kimi。"""
    if not KIMI_API_KEY and not DEEPSEEK_API_KEY:
        log.error("KIMI_API_KEY 与 DEEPSEEK_API_KEY 均未配置")
        return "（未配置 Kimi/DeepSeek API Key，无法生成分析）"

    prompt = _build_kimi_prompt(posts, stats, profile, web_supplement)
    log.info("Prompt length: %d chars (~%d tokens)", len(prompt), len(prompt) // 2)

    subject = profile.get("subject", "品牌")
    system_content = (
        f"你是资深游戏舆情与社区生态分析师，为{subject}输出舆情与社区生态观察报告，"
        "支持社区运营、市场策略、创作者生态与风险判断。不编造数据，风险判断克制。"
    )

    if DEEPSEEK_API_KEY:
        log.info("优先使用 DeepSeek API 生成报告")
        content = _analyze_with_deepseek(system_content, prompt)
        if content:
            return content
        if KIMI_API_KEY:
            log.info("DeepSeek 未返回正文或失败，改用 Kimi API")
        else:
            return "（DeepSeek 未返回正文）"

    kimi_payload = {
        "model": "moonshot-v1-128k",
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": KIMI_REPORT_MAX_TOKENS,
    }
    if KIMI_REPORT_WEB_SEARCH:
        kimi_payload["tools"] = [{"type": "builtin_function", "function": {"name": "$web_search"}}]
        kimi_payload["tool_choice"] = "auto"
    timeout_sec = 300 if KIMI_REPORT_WEB_SEARCH else 120

    try:
        resp = requests.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KIMI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=kimi_payload,
            timeout=timeout_sec,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0].get("message", {})
        content = (msg.get("content") or "").strip()
        return content or "（Kimi 未返回正文）"
    except Exception as exc:
        log.error("Kimi API error: %s", exc)
        return f"（Kimi 分析失败：{exc}）"


# ---------------------------------------------------------------------------
# Kimi 联网补充
# ---------------------------------------------------------------------------

def kimi_web_search_supplement(profile: dict) -> str:
    from datetime import timedelta, datetime
    from sentiment.config.settings import BEIJING

    if not KIMI_API_KEY or not profile.get("web_supplement"):
        return ""

    now = datetime.now(BEIJING)
    days = profile.get("days", 7)
    end_dt = (now - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
    start_dt = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = end_dt.strftime("%Y-%m-%d")
    subject = profile.get("subject", "品牌")

    prompt = f"""请使用联网搜索，检索并整理【{start_s} 至 {end_s}】期间{subject}在中国大陆社媒的舆情与讨论。

要求：
1. 覆盖微博、抖音、小红书、B站、知乎等平台的热搜、话题、讨论焦点、争议、活动相关讨论。
2. 整理成一份结构清晰的补充材料，约 3000～5000 字，分主题或分平台列出。
3. 只输出整理后的材料正文，不要"根据搜索结果"等元说明。"""

    payload = {
        "model": "moonshot-v1-128k",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    try:
        resp = requests.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KIMI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        log.info("Kimi 联网补充: %d 字", len(text))
        return text
    except Exception as exc:
        log.warning("Kimi 联网补充失败: %s", exc)
        return ""
