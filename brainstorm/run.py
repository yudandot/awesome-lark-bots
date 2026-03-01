# -*- coding: utf-8 -*-
"""
脑暴主流程 —— 坚果五仁 v3 四轮讨论协议。
==========================================

这是脑暴机器人的核心引擎，编排 5 个 AI 角色进行四轮结构化讨论：

  第 1 轮 Idea Expansion（发散）  → 产出约 10 个体验方向
  第 2 轮 Experience Embodiment   → 压缩为 6 个可执行候选
  第 3 轮 Brutal Selection（淘汰）→ 三道筛子，只留 3 个方向
  第 4 轮 Execution Conversion    → 交付物（总结 + Claude Code prompt + 视觉 prompt）

5 个角色（坚果五仁）：
  芝麻仁 — 现实架构师（DeepSeek）：负责可行性、成本、约束
  核桃仁 — 玩家化身（豆包）    ：第一人称验证体验真实性
  杏仁   — 体验导演（Kimi）    ：设计具体瞬间、情绪峰值
  瓜子仁 — 传播架构师（Kimi）  ：设计可分享单元、传播路径
  松子仁 — 体验总成（DeepSeek）：收敛、裁决、产出最终交付物

每轮结束后自动生成摘要，作为下一轮的上下文记忆。
全程结果保存到 runs/ 目录，并实时推送到飞书群。

使用方式：
  CLI  : python3 -m brainstorm --topic "主题" --context "背景"
  代码 : from brainstorm.run import run_brainstorm
"""
import argparse
import json
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.feishu_webhook import send_text, _send_card
import os as _os
from core.llm import chat_completion, get_model_for_role
from core.utils import load_context, run_timestamp, save_session, truncate_for_display
from skills import load_context as load_skill_context

def _send_brainstorm_card(title: str, content: str, color: str = "blue") -> bool:
    # 被自媒体助手调用时，优先用自媒体助手指定的脑暴推送 webhook
    webhook = (_os.environ.get("CONDUCTOR_BRAINSTORM_WEBHOOK") or _os.environ.get("FEISHU_WEBHOOK") or "").strip()
    if not webhook:
        return False
    secret = (_os.environ.get("FEISHU_SECRET") or "").strip()
    return _send_card(title, content, webhook, secret=secret, color=color)


REFINE_SYSTEM = """You are a Creative Strategy Architect.

Your task is to clarify and structure the user's raw topic into a Brainstorm Seed. Stay close to the user's original topic: do not over-interpret, over-expand, or replace it with a different brief. Preserve the core intent and wording; only add structure and clarity. Do not add assumptions or objectives the user did not imply.

Extract USER INSIGHTS and PROJECT INSIGHTS only from what the topic and materials actually imply. Keep insights concise.

You must output in the following structure:

---

INSIGHT LAYER

User Insight:
(concise; only what the topic/materials support)

Project Insight:
(nature of project, constraints, behavioral success; concise)

Campaign Context Insight:
(how participants encounter it, defining moment, after; concise)

---

Then generate the Brainstorm Seed:

---

#brainstorm

原始主题：
(Copy the user's raw topic verbatim, character for character. Do not paraphrase or rewrite.)

Theme:
(reframe only slightly; stay aligned with original topic)

Background:
(brief, from materials)

Core Challenge:
(the real difficulty implied by the topic)

Constraints:
(realistic; from topic/materials)

Core Goal:
(one clear experiential goal; do not broaden scope)

Campaign Role:
offline experiential core / online propagation trigger / hybrid campaign anchor

Campaign Phase:
Seed / Ignite / Spread / Peak / Echo

Core Task:

Design a Core Experience Atom:

When【trigger】
Participant【experiences】
Participant【emotion】
Participant【behavior】

---

Requirements:

Total length: under 500 words. Insights and theme must not expand beyond what the raw topic implies.

All output must be in Chinese (中文).

Do not use asterisks (* or **). Plain text only.

Do not over-interpret: if the topic is narrow, keep the seed narrow. If the topic does not specify something, do not invent it.

Only output the structured content; do not explain your reasoning."""


def refine_brainstorm_topic_deepseek(topic: str, context: str) -> str:
    user = f"""Input: Raw brainstorming topic and background materials below.

Output: First the INSIGHT LAYER (concise), then the Brainstorm Seed. In the #brainstorm section you must include "原始主题：" and copy the raw topic below verbatim (一字不改). Stay close to the user's topic; do not over-interpret or add objectives they did not imply. All content in Chinese (中文). No asterisks; plain text only.

---

Raw topic:
{topic}

Background materials:
{context[:8000] if len(context) > 8000 else context}"""
    try:
        return chat_completion(provider="deepseek", system=REFINE_SYSTEM, user=user).strip()
    except Exception:
        return ""


# ── 角色 & 轮次配置 ─────────────────────────────────────────
# 下面保留了两套角色系统：
# 1. legacy 八仙 —— 旧版本（已弃用，保留兼容性）
# 2. 坚果五仁 v3 —— 当前版本（从 prompts.json 加载）
# 程序启动时自动检测 prompts.json，有则用坚果五仁，无则回退八仙。

ROLES_LEGACY = [
    "Strategy Lead", "Audience Insight", "Online Growth", "Offline Experience",
    "Brand Guardian", "Conversion & Funnel", "Risk & Compliance", "Synthesizer",
]
ROLE_CN_LEGACY = {
    "Strategy Lead": ("铁拐李", "策略负责人"),
    "Audience Insight": ("汉钟离", "用户洞察"),
    "Online Growth": ("张果老", "线上增长"),
    "Offline Experience": ("吕洞宾", "线下体验"),
    "Brand Guardian": ("何仙姑", "品牌守门人"),
    "Conversion & Funnel": ("蓝采和", "转化/漏斗"),
    "Risk & Compliance": ("韩湘子", "风险/合规"),
    "Synthesizer": ("曹国舅", "收敛/交付物编排"),
}
ROUND_NAMES_LEGACY = {1: "Diverge", 2: "Align", 3: "Converge"}
ROUND_GOALS_LEGACY = {
    1: "Round 1 (Diverge): Propose 2-3 executable directions. Be concrete, no vague ideas.",
    2: "Round 2 (Align): Identify disagreements, give 2-3 options with trade-offs, and recommend one path clearly.",
    3: "Round 3 (Converge): State clear decisions, MVP scope, and action list (Owner/Support/Deadline). Synthesizer must output the full Claude Code Handoff Pack.",
}

PASS_NAMES = {1: "Idea Expansion", 2: "Experience Embodiment", 3: "Brutal Selection", 4: "Execution Conversion"}
ROUND_COLORS = {1: "blue", 2: "purple", 3: "orange", 4: "green"}
AGENT_COLORS = {"芝麻仁": "blue", "核桃仁": "orange", "杏仁": "purple", "瓜子仁": "indigo", "松子仁": "green"}
PASS_GOALS = {
    1: "第一轮 Idea Expansion：扩展可能空间，产出约 10 个体验方向。禁止收敛、禁止执行计划。每个方向必须足够具体（谁、在哪、做什么、参与者有什么反应），不接受「沉浸式体验」「VR 互动」等空洞概念。",
    2: "第二轮 Experience Embodiment：将方向转化为可被相信的亲身经历，压缩成约 6 个强体验候选。每个方向必须能回答：参与者会因此发生什么具体行为改变？激活哪种传播动机（身份/惊喜/稀缺/发现/地位）？用户最终会发一条什么样的朋友圈/小红书？回答不了的方向直接砍掉。",
    3: "第三轮 Brutal Selection：每位 agent 必须对上轮留下的每个方向逐一投「保留」或「淘汰」票并说明理由。不允许全票通过——至少一半方向必须被淘汰。三道筛：新颖性（体验模式是否已被用烂？若是则淘汰）、行为改变（带来什么具体行为改变？说不清则淘汰）、传播动机（激活身份/惊喜/稀缺/发现/地位中的哪一种？无则淘汰）。松子仁最后发言做最终裁决，只保留 3 个方向，不妥协、不合并。",
    4: "第四轮 Execution Conversion：本轮仅围绕第三轮保留的 3 个方向展开。严禁复活已淘汰方向，严禁引入新方向——违反者由松子仁当场制止。产出两样：（1）讨论总结 + 供 Claude Code 完善成具体计划和工作流的 prompt；（2）供视觉大模型生成创意概念可视化的 prompt（3 个方向各一份）。松子仁须输出上述两样。",
}
CONTROLLER_ANNOUNCE = {1: "进入第一轮：Idea Expansion", 2: "进入第二轮：Experience Embodiment", 3: "进入第三轮：Brutal Selection", 4: "进入第四轮：Execution Conversion"}

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
PROMPTS_JSON = Path(__file__).resolve().parent.parent / "prompts.json"
FEISHU_INTERVAL = 1.0

_PROMPTS_JSON_CACHE = None


def _load_prompts_json():
    global _PROMPTS_JSON_CACHE
    if _PROMPTS_JSON_CACHE is not None:
        return _PROMPTS_JSON_CACHE
    out = {"by_cn": {}, "controller_prompt": None, "roles_order": None}
    if not PROMPTS_JSON.exists():
        _PROMPTS_JSON_CACHE = out
        return out
    try:
        data = json.loads(PROMPTS_JSON.read_text(encoding="utf-8"))
        agents = data.get("agents", [])
        out["by_cn"] = {
            ag["name"]: {"system_prompt": ag["system_prompt"], "role": ag.get("role", ag["name"])}
            for ag in agents
        }
        out["controller_prompt"] = data.get("controller_prompt")
        if agents and out["controller_prompt"] and len(agents) == 5:
            out["roles_order"] = [ag["name"] for ag in agents]
        _PROMPTS_JSON_CACHE = out
        return out
    except Exception:
        _PROMPTS_JSON_CACHE = out
        return out


def _prompt_path(role: str) -> Path:
    m = {
        "Strategy Lead": "strategy_lead", "Audience Insight": "audience_insight",
        "Online Growth": "online_growth", "Offline Experience": "offline_experience",
        "Brand Guardian": "brand_guardian", "Conversion & Funnel": "conversion_funnel",
        "Risk & Compliance": "risk_compliance", "Synthesizer": "synthesizer",
    }
    name = m.get(role, role.replace(" ", "_").replace("&", "").lower())
    return PROMPTS_DIR / f"{name}.txt"


def _get_roles_and_config():
    j = _load_prompts_json()
    by_cn = j["by_cn"]
    if j["roles_order"] and len(j["roles_order"]) == 5:
        def _display_v3(role):
            r = by_cn.get(role, {}).get("role", role)
            return (role, r)
        return j["roles_order"], _display_v3, PASS_NAMES, PASS_GOALS, True
    ROLES = ROLES_LEGACY
    def _display_legacy(role):
        cn_name, default_role = ROLE_CN_LEGACY.get(role, (role, role))
        if by_cn and cn_name in by_cn and by_cn[cn_name].get("role"):
            return cn_name, by_cn[cn_name]["role"]
        return cn_name, default_role
    return ROLES, _display_legacy, ROUND_NAMES_LEGACY, ROUND_GOALS_LEGACY, False


def load_system_prompt(role: str) -> str:
    j = _load_prompts_json()
    by_cn = j["by_cn"]
    cn_name = role if role in by_cn else ROLE_CN_LEGACY.get(role, (role, role))[0]
    if by_cn and cn_name in by_cn:
        return by_cn[cn_name]["system_prompt"].strip()
    p = _prompt_path(role)
    if not p.exists():
        return "You are " + role + ". Output: One-line stance / Reason (max 3 bullets) / Actions (max 3 bullets) / Open questions (max 2, optional)."
    return p.read_text(encoding="utf-8").strip()


def get_role_display(role: str) -> tuple:
    _, display_fn, _, _, _ = _get_roles_and_config()
    return display_fn(role)


# ── 单轮执行 ────────────────────────────────────────────────
# 一轮讨论的流程：
# 1. 构建上下文（主题 + 背景 + 之前各轮摘要 + 当前轮次目标 + 风格约束）
# 2. 5 个角色按顺序发言，每人看到前 3 个人的发言并回应
# 3. 每人发言完毕后推送到飞书群
# 4. 全部发言完成后，用 AI 生成本轮摘要

def run_round(
    round_num: int,
    topic: str,
    context: str,
    deliverables: str,
    round_summaries: list[str],
    ts: str,
    brand_context: str = "",
) -> tuple[list[str], str]:
    ROLES, display_fn, round_names, round_goals, is_v3 = _get_roles_and_config()
    goal = round_goals.get(round_num, "")
    round_name = round_names.get(round_num, f"Round {round_num}")

    parts = [f"Topic: {topic}"]
    if context:
        parts.append(f"Initial context: {context}")
    if brand_context:
        parts.append(f"品牌知识参考（创意方向需符合品牌调性）：\n{brand_context}")
    if deliverables:
        parts.append(f"Requested deliverables: {deliverables}")
    for i, s in enumerate(round_summaries, 1):
        parts.append(f"--- 第 {i} 轮 Summary ---\n{s}")
    parts.append(f"\n--- 当前轮次 ---\n{goal}")
    parts.append(
        "【风格】发言必须使用中文，尽量简约精炼。像飞书群里的真实内部讨论：纯自然发言，可接上面人的话、可简短回应。"
        "禁止使用星号（* 或 **），禁止 markdown、bullet、编号列表。一律纯文本。不要咨询报告腔、不要企业黑话。"
        "每条最多 3～4 段短段，像真人打字，能一句话说清的不写长段。"
    )
    if is_v3:
        parts.append(
            "【节奏】讨论中大家要想清楚整个 campaign 的节奏：若是传播向，需明确预热、高潮、收尾；若是现场活动，需明确具体时长与体验节奏设置（例如几点到几点、每个环节多久、情绪曲线如何）。"
        )
    if is_v3 and round_num == 3:
        parts.append(
            "【第三轮纪律——严格执行】\n"
            "1. 每位 agent 必须对上轮留下的每个方向逐一表态：「保留」或「淘汰」，附一句话理由。不允许含糊或跳过。\n"
            "2. 禁止全票通过——至少一半方向必须被淘汰。如果你觉得某方向「还行但不够强」，投淘汰票。\n"
            "3. 三道筛子：新颖性（体验模式是否已被品牌/活动用烂？若是→淘汰）、行为改变（带来什么具体行为改变？说不清→淘汰）、传播动机（激活身份/惊喜/稀缺/发现/地位？无→淘汰）。\n"
            "4. 松子仁最后发言，做出不可翻转的最终裁决。只留 3 个方向，不妥协、不合并。\n"
            "5. 评价维度：行为改变、新颖性、传播动机。不按情绪基调或「听起来不错」来评价。"
        )
    if is_v3 and round_num == 4:
        parts.append(
            "【第四轮纪律——严格执行】\n"
            "本轮仅围绕第三轮松子仁裁决保留的 3 个方向展开。\n"
            "严禁复活已淘汰方向，严禁引入新方向。违反者由松子仁当场制止。\n"
            "所有讨论和产出必须聚焦于如何让这 3 个方向落地、传播、视觉化。"
        )
    if not is_v3:
        parts.append("【约束】方案需符合游戏调性与 IP，但优先做游戏外、社媒上、线下、现实场景的体验；这类体验由市场团队更可控、更好落地。")
    base_context = "\n\n".join(parts)

    messages_this_round = []
    n_roles = len(ROLES)

    for idx, role in enumerate(ROLES, 1):
        cn_name, cn_role = display_fn(role)
        print(f"    [{idx}/{n_roles}] {cn_name}（{cn_role}）发言中...", flush=True)
        system = load_system_prompt(role)
        recent = messages_this_round[-3:] if messages_this_round else []
        speak_instruction = (
            "轮到你发言了。用自然群聊体回复，简约精炼，最多 3～4 段短段。"
            "可用 **加粗** 标记关键词，可用 → 或 - 引导要点，但不要写长列表。"
            "信息密度要高——每段必须包含具体判断或信息，不允许空话套话。"
        )
        if recent:
            prior_block = "【本轮前面几个人刚说的——你必须回应其中至少一位的观点（同意+补充具体内容 或 反对+理由），禁止忽略前面的发言自说自话】\n\n"
            for r, m in recent:
                pn, pr = display_fn(r)
                prior_block += f"{pn}（{pr}）：\n{m}\n\n"
            user = base_context + "\n\n" + prior_block + speak_instruction
        else:
            user = base_context + "\n\n" + speak_instruction
        if not is_v3 and round_num == 3 and role == "Synthesizer":
            user += " 最后必须附上完整的 Claude Code Handoff Pack（A 决策与理由、B 行动清单、C 可复制块）。"

        provider = get_model_for_role(role)
        raw = chat_completion(provider=provider, system=system, user=user)
        display = truncate_for_display(raw)
        messages_this_round.append((role, display))

        round_label = f"第{round_num}轮 {round_name}" if is_v3 else f"Round {round_num}"
        card_title = f"{cn_name}（{cn_role}）| {round_label}"
        card_color = AGENT_COLORS.get(cn_name, ROUND_COLORS.get(round_num, "blue"))
        _send_brainstorm_card(card_title, display, color=card_color)
        print(f"    [{idx}/{n_roles}] {cn_name}（{cn_role}）完成 ({len(display)} 字) 已推送到飞书", flush=True)
        time.sleep(FEISHU_INTERVAL)

    print(f"  [第{round_num}轮] 生成本轮摘要...", flush=True)
    summary_prompt = (
        "用中文把下面这场讨论总结成 8～12 行。必须包含：本轮讨论到的所有创意/方向（逐一列出），主要分歧（如有），已定的结论或下一步。"
        "语气像真人做的会议纪要，不要套话。可用 **加粗** 标记关键词，可用 - 列要点，段间留空行。只输出摘要，不要加标题。"
    )
    full_round_text = "\n\n".join(f"[{r}]\n{msg}" for r, msg in messages_this_round)
    provider_summary = get_model_for_role(ROLES[0])
    round_summary = chat_completion(
        provider=provider_summary,
        system="你是会议记录员，用中文写简洁、口语化的会议摘要。可用 **加粗** 和 - 列表增强可读性。",
        user=summary_prompt + "\n\n" + full_round_text,
    )
    round_summary = truncate_for_display(round_summary)
    print(f"  [第{round_num}轮] 摘要完成", flush=True)
    return messages_this_round, round_summary


# ── 完整脑暴流程 ─────────────────────────────────────────────
# 完整流程：
# 1. DeepSeek 将原始主题优化为结构化的 Brainstorm Seed
# 2. 执行 4 轮讨论（每轮 5 个角色依次发言 → 生成摘要）
# 3. Kimi 根据 4 轮摘要生成最终交付物（讨论总结 + Claude Code prompt + 视觉 prompt）
# 4. 保存完整 session 到 runs/ 目录

def run_brainstorm(
    topic: str,
    context: str = "",
    deliverables: str = "",
    no_refine: bool = False,
    brand: str = "",
) -> str:
    """执行完整的脑暴流程，返回 session 文件路径。

    brand: 可选，指定品牌名。留空则自动从 topic/context 中检测。
    """
    if not deliverables:
        deliverables = "方案文档（md）、执行清单（md）、飞书群公告/brief（md）"

    brand_context = ""
    if brand:
        brand_context = load_skill_context("brand", brand_name=brand)
    else:
        brand_context = load_skill_context("brand", detect_from=f"{topic} {context}")
    if brand_context:
        print(f"[品牌知识] 已加载品牌知识，将注入到讨论上下文中。", flush=True)

    ts = run_timestamp()
    round_summaries: list[str] = []
    session_lines = [
        f"# Session {ts}",
        f"Topic (raw): {topic}",
        f"Context: {context}",
        f"Deliverables: {deliverables}",
        "",
    ]

    if not no_refine:
        print("[DeepSeek] 正在优化脑暴主题与讨论思路...", flush=True)
        refined = refine_brainstorm_topic_deepseek(topic, context)
        if refined:
            topic = refined
            session_lines.append("DeepSeek 优化后的主题与思路：")
            session_lines.append("")
            session_lines.append(refined)
            session_lines.append("")
            session_lines.append("---")
            session_lines.append("")
            print("[DeepSeek] 已确定主题与思路。", flush=True)
            _send_brainstorm_card("本场脑暴主题", truncate_for_display(refined), color="indigo")
            time.sleep(FEISHU_INTERVAL)
        else:
            print("[DeepSeek] 调用失败，使用原始主题。", flush=True)

    session_lines[1] = f"Topic: {topic}"

    ROLES, display_fn, round_names, round_goals, is_v3 = _get_roles_and_config()
    num_rounds = 4 if is_v3 else 3
    if is_v3:
        session_lines.append("Controller: 坚果五仁体验创新 v3.0，四轮协议")
        session_lines.append("")
    print(f"[脑暴开始] 主题: {topic[:120]}{'...' if len(topic) > 120 else ''}", flush=True)
    if context:
        print(f"  背景: {context[:80]}{'...' if len(context) > 80 else ''}", flush=True)
    print("", flush=True)

    for round_num in range(1, num_rounds + 1):
        round_name = round_names.get(round_num, f"Round {round_num}")
        goal = round_goals.get(round_num, "")

        print(f"========== 第 {round_num} 轮 / {round_name} ==========", flush=True)

        if is_v3:
            controller_msg = CONTROLLER_ANNOUNCE.get(round_num, f"进入第{round_num}轮")
            print(f"  [Controller] {controller_msg}", flush=True)
            round_color = ROUND_COLORS.get(round_num, "blue")
            _send_brainstorm_card(f"第 {round_num} 轮：{round_name}", controller_msg, color=round_color)
            session_lines.append("## " + controller_msg)
        else:
            header = f"Round {round_num} / {round_name} / 主题: {topic} / 目标与约束: {goal}"
            print(f"  [飞书] 发送本轮开场...", flush=True)
            _send_brainstorm_card(f"Round {round_num}: {round_name}", header, color=ROUND_COLORS.get(round_num, "blue"))
            session_lines.append("## " + header)
        session_lines.append("")
        time.sleep(FEISHU_INTERVAL)

        print(f"  [第{round_num}轮] {len(ROLES)} 个角色依次发言中...", flush=True)
        messages_this_round, round_summary = run_round(
            round_num=round_num, topic=topic, context=context,
            deliverables=deliverables, round_summaries=round_summaries, ts=ts,
            brand_context=brand_context,
        )
        round_summaries.append(round_summary)

        for role, msg in messages_this_round:
            cn_name, cn_role = display_fn(role)
            round_label = f"第{round_num}轮 {round_name}" if is_v3 else f"Round {round_num}"
            session_lines.append(f"### {cn_name}（{cn_role}）| {round_label}")
            session_lines.append("")
            session_lines.append(msg)
            session_lines.append("")
        session_lines.append("### 第" + str(round_num) + "轮 Summary")
        session_lines.append("")
        session_lines.append(round_summary)
        session_lines.append("")
        session_lines.append("---")
        session_lines.append("")

    if is_v3 and round_summaries:
        print("[最终交付] 由 Kimi 生成讨论总结 + Claude Code prompt、视觉大模型 prompt...", flush=True)
        summary_input = f"主题：{topic}\n\n各轮摘要：\n" + "\n\n".join(f"第{i}轮：{s}" for i, s in enumerate(round_summaries, 1))
        final_system = (
            "你是体验创新流程的交付整理员。根据以下四轮讨论摘要，输出两样内容，分开写、标题明确。全文必须使用中文。"
            "可用 **加粗** 标记关键词，可用 - 列要点，段间留空行，提高可读性。\n\n"
            "【交付一】讨论总结 + 供 Claude Code 完善成具体计划和工作流的 prompt\n"
            "1. 讨论总结：先逐一列出四轮中讨论过的所有创意/方向（第一轮约 10 个、第二轮 6 个、第三轮留下 3 个），"
            "再用 3～5 段自然段概括结论、共识与最终留下的 3 个体验方向。\n"
            "2. Claude Code 用 prompt：写一段可直接复制给 Claude Code 的完整 prompt，说明请其根据上述讨论总结，"
            "完善成具体执行计划和工作流（含步骤、负责人建议、产出物、验收标准、时间节点等），便于 Claude Code 据此输出可落地的计划与工作流。\n\n"
            "【交付二】供视觉大模型生成的创意概念可视化的 prompt\n"
            "为上述 3 个体验方向各写一份可直接交给图像/视频大模型使用的 prompt。每份须包含："
            "（1）能够可视化的体验参考——场景、光线、氛围、关键瞬间、人物动作等，语言简洁、适合作生成模型输入；"
            "须自动加入符合品牌调性的风格描述（如色彩、质感、情绪基调、视觉语言）。"
            "（2）用户角度的创意脚本——从用户视角可被拍摄/讲述的脚本或梗概，须有传播力（易被转发、可引发共鸣或讨论、具备记忆点）。"
        )
        try:
            final_output = chat_completion(provider="kimi", system=final_system, user=summary_input).strip()
            session_lines.append("## 最终交付（两样）")
            session_lines.append("")
            session_lines.append(final_output)
            session_lines.append("")
            to_feishu = final_output if len(final_output) <= 8000 else final_output[:8000] + "\n\n[内容过长，完整交付请查看 session 文件]"
            _send_brainstorm_card("最终交付", to_feishu, color="green")
            time.sleep(FEISHU_INTERVAL)
        except Exception as e:
            print(f"[最终交付] 生成失败: {e}", flush=True)

    session_content = "\n".join(session_lines)
    path = save_session(session_content, ts)
    print("[保存] 会话已写入 " + str(path), flush=True)

    if is_v3:
        _send_brainstorm_card("脑暴结束", f"完整会话已保存至 `{path}`", color="green")
    else:
        _send_brainstorm_card("脑暴结束", f"完整会话与 Handoff Pack 已保存至 `{path}`", color="green")
    print("\n========== 脑暴结束 ==========", flush=True)
    return str(path)


# ── CLI 入口 ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AIlarkteams 脑暴")
    parser.add_argument("--topic", required=True, help="脑暴主题")
    parser.add_argument("--context", default="", help="背景材料：文本，或文件/目录路径")
    parser.add_argument("--deliverables", default="", help="期望交付物")
    parser.add_argument("--no-refine", action="store_true", help="跳过 DeepSeek 主题优化")
    parser.add_argument("--brand", default="", help="指定品牌名（如 sky），留空则自动检测")
    args = parser.parse_args()
    run_brainstorm(
        topic=args.topic.strip(),
        context=load_context(args.context or ""),
        deliverables=(args.deliverables or "").strip(),
        no_refine=args.no_refine,
        brand=(args.brand or "").strip(),
    )


if __name__ == "__main__":
    main()
