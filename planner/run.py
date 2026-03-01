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
from planner.prompts import REFINE_BRIEF_SYSTEM, STEP_PROMPTS, MODES, MODE_DESCRIPTIONS, PLANNER_SYSTEM
from skills import load_context as load_skill_context

FEISHU_INTERVAL = 1.0
PROVIDER = "deepseek"


def _load_skills_context() -> str:
    """通过共享技能库加载营销知识摘要，为规划提供领域知识参考。"""
    return load_skill_context("marketing", max_modules=10, header_chars=500)


def refine_brief(topic: str, context: str) -> str:
    skills = _load_skills_context()
    user_msg = f"原始需求：\n{topic}\n\n背景材料：\n{context[:8000] if len(context) > 8000 else context}"
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
    step_cfg = STEP_PROMPTS[step_num]
    system = step_cfg["system"]
    instruction = step_cfg["instruction"]
    parts = [f"规划主题：{topic}"]
    if context:
        parts.append(f"背景材料：{context[:6000]}")
    for prev_num, prev_name, prev_output in previous_outputs:
        parts.append(f"--- 第 {prev_num} 步 {prev_name} 的输出 ---\n{prev_output}")
    parts.append(instruction)
    parts.append("如果加载了领域知识/框架 skill，在分析中显式调用。标了「如相关才写」的字段，不相关就跳过。")
    user_msg = "\n\n".join(parts)
    try:
        from core.skill_router import enrich_prompt
        system = enrich_prompt(system, user_text=user_msg, bot_type="planner")
    except Exception:
        pass
    return chat_completion(provider=PROVIDER, system=system, user=user_msg).strip()


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


def run_planning(
    topic: str,
    context: str = "",
    mode: str = "完整规划",
    no_refine: bool = False,
) -> str:
    """执行完整的理性规划流程，返回 session 文件路径。"""
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
    send_planner_card("规划完成", f"完整内容已保存至 `{path}`", color="green")
    print("\n========== 规划结束 ==========", flush=True)
    return str(path)


def main():
    parser = argparse.ArgumentParser(description="理性规划 AI 助手")
    parser.add_argument("--topic", required=True, help="规划主题")
    parser.add_argument("--context", default="", help="背景材料")
    parser.add_argument("--mode", default="完整规划", choices=list(MODES.keys()), help="规划模式")
    parser.add_argument("--no-refine", action="store_true", help="跳过需求结构化")
    args = parser.parse_args()
    run_planning(
        topic=args.topic.strip(),
        context=load_context(args.context or ""),
        mode=args.mode,
        no_refine=args.no_refine,
    )


if __name__ == "__main__":
    main()
