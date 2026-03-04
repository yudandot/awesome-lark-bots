# -*- coding: utf-8 -*-
"""
规划机器人主流程 —— 理性六步结构化决策引擎。
=============================================

这是规划机器人的核心引擎，将用户的问题通过结构化流程转化为可执行方案。

完整规划流程（六步）：
  第 1 步 问题定义  → 明确目标、约束、成功标准
  第 2 步 现状分析  → 当前状态、资源、风险
  第 3 步 方案生成  → 3 个截然不同的战略方案
  第 4 步 评估矩阵  → 多维打分比较，推荐最佳方案
  第 5 步 执行计划  → 3-5 步具体行动，含时间和产出
  第 6 步 反馈机制  → 先行/滞后指标、检查节点、止损线

支持 5 种模式：
  完整规划 : 六步全走
  快速模式 : 第1→3→4→5步（跳过现状分析和反馈机制）
  分析模式 : 仅第1→2步
  方案模式 : 仅第3步
  执行模式 : 仅第5步

每一步的结果实时推送到飞书群，最后生成规划摘要。

使用方式：
  CLI  : python3 -m planner --topic "Q3 增长策略" --mode "快速模式"
  代码 : from planner.run import run_planning
"""
import argparse
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core.feishu_webhook import send_planner_text as send_text, send_planner_card
from core.llm import chat_completion
from core.utils import load_context, run_timestamp, save_session, truncate_for_display
from planner.prompts import (
    REFINE_BRIEF_SYSTEM, STEP_PROMPTS, MODES, MODE_DESCRIPTIONS, PLANNER_SYSTEM, DOC_TYPES,
    SEARCH_JUDGE_SYSTEM, SEARCH_CONTEXT_SYSTEM,
)
from skills import load_context as load_skill_context

FEISHU_INTERVAL = 1.0
PROVIDER = "deepseek"


_MARKETING_SIGNALS = (
    "营销", "推广", "增长", "获客", "品牌", "内容", "运营", "投放",
    "小红书", "抖音", "B站", "微博", "快手", "平台", "社媒",
    "marketing", "growth", "campaign", "content",
)


def _load_skills_context(topic: str = "") -> str:
    """话题与营销相关时才加载营销知识，否则跳过。"""
    if topic:
        lower = topic.lower()
        if not any(kw in lower for kw in _MARKETING_SIGNALS):
            return ""
    return load_skill_context("marketing", max_modules=10, header_chars=500)


def refine_brief(topic: str, context: str) -> str:
    skills = _load_skills_context(topic)
    user_msg = f"原始需求：\n{topic}\n\n背景材料：\n{context[:30000] if len(context) > 30000 else context}"
    if skills:
        user_msg += f"\n\n{skills[:4000]}"
    user_msg += "\n\n请将上述需求结构化为 Planning Brief。保持原始意图，不要过度解读。使用中文。"
    try:
        from core.skill_router import enrich_prompt
        sys = enrich_prompt(REFINE_BRIEF_SYSTEM, user_text=user_msg, bot_type="planner")
        return chat_completion(provider=PROVIDER, system=sys, user=user_msg).strip()
    except Exception:
        return ""


def run_step(step_num: int, topic: str, context: str, previous_outputs: list[tuple[int, str, str]]) -> str:
    """用 AgentLoop 执行规划步骤——LLM 在思考过程中可随时搜索补充信息。"""
    from core.agent import AgentLoop
    from core.tools import WEB_SEARCH_TOOL, NEWS_SEARCH_TOOL, FETCH_URL_TOOL, TRENDING_TOOL

    step_cfg = STEP_PROMPTS[step_num]
    system = step_cfg["system"]
    instruction = step_cfg["instruction"]

    system += (
        "\n\n你拥有搜索工具。如果在分析过程中需要数据支撑（市场数据、竞品信息、行业趋势、"
        "政策法规等），请主动调用工具搜索，不要凭空编造数据。"
        "但也不要过度搜索——只在确实需要外部信息时才用。"
    )

    try:
        from core.skill_router import enrich_prompt
        system = enrich_prompt(system, user_text=topic, bot_type="planner")
    except Exception:
        pass

    parts = [f"规划主题：{topic}"]
    if context:
        parts.append(f"背景材料：{context[:20000]}")
    for prev_num, prev_name, prev_output in previous_outputs:
        parts.append(f"--- 第 {prev_num} 步 {prev_name} 的输出 ---\n{prev_output}")
    parts.append(instruction)
    parts.append("标了「如相关才写」的字段，不相关就跳过。像正常人说话，不要贴框架名当标签。")
    user_msg = "\n\n".join(parts)

    try:
        agent = AgentLoop(
            provider=PROVIDER,
            system=system,
            max_rounds=5,
            temperature=0.7,
            on_tool_call=lambda name, args: print(f"  🔍 [{name}] {str(args)[:80]}", flush=True),
        )
        from skills import collect_tools as _collect_skill_tools
        agent.add_tools([WEB_SEARCH_TOOL, NEWS_SEARCH_TOOL, FETCH_URL_TOOL, TRENDING_TOOL]
                        + _collect_skill_tools())
        result = agent.run(user_msg)
        if result.tool_calls_made:
            print(f"  [第{step_num}步] 搜索了 {len(result.tool_calls_made)} 次", flush=True)
        return result.content
    except Exception as e:
        print(f"[规划] 第{step_num}步 AgentLoop 失败({e}), 回退到简单调用", flush=True)
        try:
            return chat_completion(provider=PROVIDER, system=system, user=user_msg).strip()
        except Exception as e2:
            print(f"[规划] 第{step_num}步 回退也失败: {e2}", flush=True)
            return f"（第{step_num}步生成失败，请稍后重试）"


def _judge_search_need(topic: str, context: str) -> dict:
    """让 LLM 判断话题是否需要联网搜索，返回 {need_search, reason, queries}。"""
    import json as _json
    user_msg = f"规划话题：{topic}"
    if context:
        user_msg += f"\n\n背景材料摘要：{context[:1000]}"
    try:
        raw = chat_completion(
            provider=PROVIDER, system=SEARCH_JUDGE_SYSTEM, user=user_msg,
        ).strip()
        import re as _re
        m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, _re.DOTALL)
        if m:
            raw = m.group(1)
        else:
            raw = raw.strip("`").removeprefix("json").strip()
        return _json.loads(raw)
    except Exception as e:
        print(f"[搜索判断] 解析失败: {e}", flush=True)
        return {"need_search": False, "reason": "判断失败", "queries": []}


def _execute_searches(queries: list[str], max_results: int = 4) -> str:
    """执行搜索并拼接原始结果文本。"""
    from research.search import web_search
    all_results: list[str] = []
    for q in queries[:3]:
        print(f"  🔍 搜索: {q}", flush=True)
        results = web_search(q, max_results=max_results)
        if results:
            parts = [f"[查询] {q}"]
            for r in results:
                title = r.get("title", "")
                content = r.get("content", "")
                url = r.get("url", "")
                parts.append(f"- {title}: {content}" + (f" ({url})" if url else ""))
            all_results.append("\n".join(parts))
    return "\n\n".join(all_results)


def _synthesize_search(topic: str, raw_results: str) -> str:
    """用 LLM 将搜索原始结果浓缩为规划可用的背景材料。"""
    if not raw_results.strip():
        return ""
    user_msg = f"规划话题：{topic}\n\n搜索结果：\n{raw_results[:6000]}"
    try:
        return chat_completion(
            provider=PROVIDER, system=SEARCH_CONTEXT_SYSTEM, user=user_msg,
        ).strip()
    except Exception as e:
        print(f"[搜索整合] 失败: {e}", flush=True)
        return ""


def research_for_planning(topic: str, context: str) -> str:
    """规划前的信息补充：判断 → 搜索 → 整合。返回补充材料或空字符串。"""
    print("[信息补充] 判断是否需要联网搜索…", flush=True)
    judgment = _judge_search_need(topic, context)

    if not judgment.get("need_search"):
        reason = judgment.get("reason", "")
        print(f"[信息补充] 不需要搜索 — {reason}", flush=True)
        return ""

    queries = judgment.get("queries") or []
    if not queries:
        print("[信息补充] 需要搜索但未生成查询词，跳过", flush=True)
        return ""

    reason = judgment.get("reason", "")
    print(f"[信息补充] 需要搜索 — {reason}", flush=True)
    print(f"[信息补充] 查询词: {queries}", flush=True)

    send_planner_card(
        "🔍 信息补充",
        f"话题需要实时数据，正在搜索…\n\n"
        + "\n".join(f"- {q}" for q in queries),
        color="blue",
    )
    time.sleep(FEISHU_INTERVAL)

    raw = _execute_searches(queries)
    if not raw.strip():
        print("[信息补充] 搜索无结果", flush=True)
        return ""

    synthesis = _synthesize_search(topic, raw)
    if synthesis:
        print(f"[信息补充] 整合完成 ({len(synthesis)} 字)", flush=True)
        send_planner_card(
            "🔍 搜索结果摘要",
            synthesis[:2000],
            color="blue",
        )
        time.sleep(FEISHU_INTERVAL)
    return synthesis


def detect_mode(text: str) -> str:
    lower = text.strip().lower()
    if "快速" in lower or "fast" in lower:
        return "快速模式"
    if "分析" in lower and "模式" in lower:
        return "分析模式"
    if "方案" in lower and "模式" in lower:
        return "方案模式"
    if "执行" in lower and "模式" in lower:
        return "执行模式"
    return "完整规划"


_DOC_QUALITY_SUFFIX = """

请根据以上规划分析生成文档。质量要求：
- 只写这个具体项目的内容，不要输出套在任何项目上都成立的通用句子
- 每句话删掉后如果不影响理解，说明这句话是废话，不要写
- 数字、时间、地点、人要具体，不要用"相关""适当""一定程度"等模糊词
- 方案描述要讲清楚核心机制（怎么运作、凭什么能行），不是口号
- 风险和卡点要写这个项目特有的，不要写所有项目都会遇到的通用风险"""


def generate_doc(
    doc_type: str,
    topic: str,
    planning_outputs: list[tuple[int, str, str]],
    audience: str = "",
) -> tuple[str, str]:
    """根据规划输出生成指定类型的可交付文档。

    Args:
        audience: 可选受众描述（如"给老板看""给执行团队"），影响内容深度和表述。

    Returns: (content, format) — format 为 "doc" 或 "sheet"。
    """
    cfg = DOC_TYPES.get(doc_type)
    if not cfg:
        return f"不支持的文档类型: {doc_type}", "doc"
    fmt = cfg.get("format", "doc")
    system = cfg["system"]
    if audience:
        system += f"\n\n受众：这份文档的读者是「{audience}」，请调整内容深度和表述方式以适配受众。"
    try:
        from core.skill_router import enrich_prompt
        system = enrich_prompt(system, user_text=topic, bot_type="planner")
    except Exception:
        pass
    context_parts = [f"规划主题：{topic}"]
    for num, name, out in planning_outputs:
        context_parts.append(f"--- 第 {num} 步 {name} ---\n{out}")
    user_msg = "\n\n".join(context_parts)
    user_msg += _DOC_QUALITY_SUFFIX
    content = chat_completion(provider=PROVIDER, system=system, user=user_msg).strip()

    if fmt == "doc":
        try:
            from planner.prompts import DOC_SELF_REVIEW_SYSTEM
            content = chat_completion(
                provider=PROVIDER,
                system=DOC_SELF_REVIEW_SYSTEM,
                user=f"文档类型：{cfg['name']}\n规划主题：{topic}\n\n---\n\n{content}",
            ).strip()
        except Exception as e:
            print(f"[文档自审] 失败，使用原始版本: {e}", flush=True)

    return content, fmt


def run_planning(
    topic: str,
    context: str = "",
    mode: str = "完整规划",
    no_refine: bool = False,
) -> tuple[str, list[tuple[int, str, str]]]:
    """执行完整的理性规划流程，返回 (session 文件路径, 规划步骤输出列表)。"""
    ts = run_timestamp()
    steps = MODES.get(mode, MODES["完整规划"])
    mode_desc = MODE_DESCRIPTIONS.get(mode, mode)

    session_lines = [
        f"# 理性规划 Session {ts}",
        f"主题（原始）：{topic}",
        f"背景：{context[:200]}{'...' if len(context) > 200 else ''}",
        f"模式：{mode}（{mode_desc}）",
        "",
    ]

    if not no_refine:
        print("[需求结构化] 正在将原始需求转化为 Planning Brief...", flush=True)
        brief = refine_brief(topic, context)
        if brief:
            session_lines.extend(["## Planning Brief（需求结构化）", "", brief, "", "---", ""])
            print("[需求结构化] 完成。", flush=True)
            send_planner_card("理性规划启动", f"**模式：**{mode}\n\n{truncate_for_display(brief)}", color="indigo")
            time.sleep(FEISHU_INTERVAL)
            context = brief + "\n\n" + context
        else:
            print("[需求结构化] 调用失败，使用原始输入。", flush=True)

    # 每个规划步骤自带搜索工具，无需预搜索。
    # 保留 research_for_planning 用于显式"研究 XX"命令。

    print(f"[规划开始] 模式: {mode}", flush=True)
    print(f"  主题: {topic[:120]}{'...' if len(topic) > 120 else ''}", flush=True)
    print(f"  步骤: {', '.join(STEP_PROMPTS[s]['name'] for s in steps)}", flush=True)
    print("", flush=True)

    step_flow = " → ".join(STEP_PROMPTS[s]["name"] for s in steps)
    send_planner_card("开始规划", f"**主题：**{topic[:200]}\n**模式：**{mode}\n**步骤：**{step_flow}", color="blue")
    time.sleep(FEISHU_INTERVAL)

    previous_outputs: list[tuple[int, str, str]] = []

    step_colors = {1: "blue", 2: "blue", 3: "purple", 4: "orange", 5: "green", 6: "blue"}

    for step_num in steps:
        step_name = STEP_PROMPTS[step_num]["name"]
        print(f"========== 第 {step_num} 步 / {step_name} ==========", flush=True)

        output = run_step(step_num=step_num, topic=topic, context=context, previous_outputs=previous_outputs)
        display = truncate_for_display(output)
        previous_outputs.append((step_num, step_name, display))

        session_lines.extend([f"## 第 {step_num} 步：{step_name}", "", output, "", "---", ""])
        card_color = step_colors.get(step_num, "blue")
        send_planner_card(f"第 {step_num} 步：{step_name}", display, color=card_color)
        print(f"  [第{step_num}步] {step_name} 完成 ({len(display)} 字) 已推送到飞书", flush=True)
        time.sleep(FEISHU_INTERVAL)

    print("[最终总结] 生成规划摘要...", flush=True)
    summary_parts = "\n\n".join(f"第 {num} 步 {name}：\n{out}" for num, name, out in previous_outputs)
    summary_system = (
        "根据规划步骤的输出，生成摘要。只写三样东西："
        "1）一句话核心结论（你的判断，不是中性总结）；"
        "2）推荐方案及理由（≤3 句）；"
        "3）用户现在就该做的第一件事。"
        "≤200 字。中文。**加粗** 关键词。"
    )
    try:
        summary = chat_completion(
            provider=PROVIDER, system=summary_system,
            user=f"规划主题：{topic}\n\n{summary_parts}\n\n请生成规划摘要。",
        ).strip()
        session_lines.extend(["## 规划摘要", "", summary, ""])
        send_planner_card("规划摘要", truncate_for_display(summary), color="green")
        time.sleep(FEISHU_INTERVAL)
    except Exception as e:
        print(f"[最终总结] 生成失败: {e}", flush=True)

    session_content = "\n".join(session_lines)
    path = save_session(session_content, f"{ts}_planning")
    print(f"[保存] 规划已写入 {path}", flush=True)
    send_planner_card(
        "规划完成",
        f"完整内容已保存至 `{path}`\n\n💬 私聊 planner bot 可追问规划内容或生成文档",
        color="green",
    )
    print("\n========== 规划结束 ==========", flush=True)
    return str(path), previous_outputs


def main():
    parser = argparse.ArgumentParser(description="理性规划 AI 助手")
    parser.add_argument("--topic", required=True, help="规划主题")
    parser.add_argument("--context", default="", help="背景材料")
    parser.add_argument("--mode", default="完整规划", choices=list(MODES.keys()), help="规划模式")
    parser.add_argument("--no-refine", action="store_true", help="跳过需求结构化")
    args = parser.parse_args()
    path, _ = run_planning(
        topic=args.topic.strip(),
        context=load_context(args.context or ""),
        mode=args.mode,
        no_refine=args.no_refine,
    )


if __name__ == "__main__":
    main()
