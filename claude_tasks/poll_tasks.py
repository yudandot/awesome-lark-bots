# -*- coding: utf-8 -*-
"""
poll_tasks.py — 从飞书 Bitable 看板拉取待处理的 @claude 任务。

用法：
    python -m claude_tasks.poll_tasks          # 输出 JSON 到 stdout
    python -m claude_tasks.poll_tasks --pretty  # 格式化输出

输出格式 (JSON):
    [
      {
        "record_id": "recXXX",
        "memo_id": "uuid",
        "thread": "dev",
        "content": "调研竞品定价策略",
        "status": "进行中",
        "partition": "今日新增",
        "created": "2026-03-09",
        "claude_note": ""           // 空 = 尚未处理
      },
      ...
    ]

退出码：
    0 — 成功（即使无任务，也输出空数组 []）
    1 — 配置缺失或 API 错误
"""
import json
import os
import sys

# ── 确保项目根在 sys.path 中 ──
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── 加载 .env ──
_env_path = os.path.join(_PROJECT_ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key and not os.environ.get(key):
                    os.environ[key] = val

# ── 设置助理 bot 的飞书凭证 ──
_app_id = (os.environ.get("ASSISTANT_FEISHU_APP_ID")
           or os.environ.get("FEISHU_APP_ID") or "")
_app_secret = (os.environ.get("ASSISTANT_FEISHU_APP_SECRET")
               or os.environ.get("FEISHU_APP_SECRET") or "")
if _app_id:
    os.environ["FEISHU_APP_ID"] = _app_id
if _app_secret:
    os.environ["FEISHU_APP_SECRET"] = _app_secret


def _load_board_config() -> dict:
    cfg_path = os.path.join(_PROJECT_ROOT, "data", "bitable_board.json")
    if not os.path.exists(cfg_path):
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


def poll(only_pending: bool = True) -> list[dict]:
    """拉取看板中的 @claude 任务。

    Args:
        only_pending: True 则只返回 Claude备注 为空的任务（未处理）
    """
    cfg = _load_board_config()
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        print("[poll_tasks] 看板未初始化 (data/bitable_board.json 不存在或缺少 app_token/table_id)",
              file=sys.stderr)
        return []

    from core.feishu_client import list_bitable_records

    ok, records = list_bitable_records(app_token, table_id)
    if not ok:
        print(f"[poll_tasks] 拉取看板记录失败: {records}", file=sys.stderr)
        return []

    tasks = []
    for rec in (records or []):
        fields = rec.get("fields") or {}
        assignee = fields.get("执行者", "")
        # 执行者字段可能是 str 或 dict (单选字段两种格式)
        if isinstance(assignee, dict):
            assignee = assignee.get("value", "") or assignee.get("name", "")
        if not assignee or "claude" not in str(assignee).lower():
            continue

        claude_note = fields.get("Claude备注", "") or ""
        if only_pending and claude_note.strip():
            continue

        tasks.append({
            "record_id": rec.get("record_id", ""),
            "memo_id": fields.get("memo_id", ""),
            "thread": fields.get("线程", ""),
            "content": fields.get("内容", ""),
            "status": fields.get("状态", ""),
            "partition": fields.get("分区", ""),
            "created": fields.get("创建时间", ""),
            "claude_note": claude_note,
            "partner_feedback": fields.get("搭档反馈", "") or "",
        })

    return tasks


def scan_board(skip_noted: bool = True) -> dict:
    """扫描看板全部待办任务，按角色分组。

    Args:
        skip_noted: True 则跳过 Claude备注 已有内容的任务

    Returns:
        {
            "claude_tasks": [...],    # 执行者=Claude 的待处理任务
            "other_tasks": [...],     # 非 Claude 指派的待办任务
        }
    """
    cfg = _load_board_config()
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        print("[poll_tasks] 看板未初始化", file=sys.stderr)
        return {"claude_tasks": [], "other_tasks": []}

    from core.feishu_client import list_bitable_records

    ok, records = list_bitable_records(app_token, table_id)
    if not ok:
        print(f"[poll_tasks] 拉取看板记录失败: {records}", file=sys.stderr)
        return {"claude_tasks": [], "other_tasks": []}

    claude_tasks = []
    other_tasks = []

    for rec in (records or []):
        fields = rec.get("fields") or {}

        # 状态处理
        status = fields.get("状态", "")
        if isinstance(status, dict):
            status = status.get("value", "") or status.get("name", "")

        partner_feedback = fields.get("搭档反馈", "") or ""

        # 跳过已完成（但有搭档反馈的除外——需要重新处理）
        if status == "已完成" and not partner_feedback.strip():
            continue

        assignee = fields.get("执行者", "")
        if isinstance(assignee, dict):
            assignee = assignee.get("value", "") or assignee.get("name", "")

        claude_note = fields.get("Claude备注", "") or ""
        # partner_feedback 已在上面提取

        # 有搭档反馈的任务始终保留（需要处理反馈）
        if skip_noted and claude_note.strip() and not partner_feedback.strip():
            continue

        task = {
            "record_id": rec.get("record_id", ""),
            "memo_id": fields.get("memo_id", ""),
            "thread": fields.get("线程", ""),
            "content": fields.get("内容", ""),
            "status": status,
            "partition": fields.get("分区", ""),
            "created": fields.get("创建时间", ""),
            "assignee": str(assignee),
            "claude_note": claude_note,
            "partner_feedback": partner_feedback,
        }

        if assignee and "claude" in str(assignee).lower():
            claude_tasks.append(task)
        else:
            other_tasks.append(task)

    # 单独提取有搭档反馈的任务（最高优先级）
    feedback_tasks = [
        t for t in claude_tasks + other_tasks
        if t.get("partner_feedback", "").strip()
    ]

    return {
        "feedback_tasks": feedback_tasks,
        "claude_tasks": claude_tasks,
        "other_tasks": other_tasks,
    }


def poll_feedback() -> list[dict]:
    """拉取所有含搭档反馈的任务（不论执行者是谁）。

    返回 partner_feedback 非空的任务列表，用于 Claude 处理反馈回复。
    """
    cfg = _load_board_config()
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        return []

    from core.feishu_client import list_bitable_records

    ok, records = list_bitable_records(app_token, table_id)
    if not ok:
        return []

    tasks = []
    for rec in (records or []):
        fields = rec.get("fields") or {}
        feedback = fields.get("搭档反馈", "") or ""
        if not feedback.strip():
            continue

        # 有反馈就保留，即使已完成（说明搭档要求改进）
        status = fields.get("状态", "")
        if isinstance(status, dict):
            status = status.get("value", "") or status.get("name", "")

        assignee = fields.get("执行者", "")
        if isinstance(assignee, dict):
            assignee = assignee.get("value", "") or assignee.get("name", "")

        tasks.append({
            "record_id": rec.get("record_id", ""),
            "memo_id": fields.get("memo_id", ""),
            "thread": fields.get("线程", ""),
            "content": fields.get("内容", ""),
            "status": status,
            "assignee": str(assignee),
            "claude_note": fields.get("Claude备注", "") or "",
            "partner_feedback": feedback,
        })

    return tasks


def load_profile_context() -> str:
    """加载搭档的 collaboration profile 摘要。"""
    try:
        from skills.personal import PersonalSkill
        skill = PersonalSkill()
        path = skill._find_profile_path()
        if not path:
            return ""
        return skill._load_md(path, bot_type="assistant")
    except Exception:
        return ""


def main():
    pretty = "--pretty" in sys.argv
    show_context = "--with-context" in sys.argv
    scan_all = "--scan-all" in sys.argv
    feedback_only = "--feedback" in sys.argv
    indent = 2 if pretty else None

    try:
        if feedback_only:
            # 反馈模式：只返回有搭档反馈的任务
            tasks = poll_feedback()
            print(json.dumps(tasks, ensure_ascii=False, indent=indent))
        elif scan_all:
            # 全量扫描模式：返回 claude_tasks + other_tasks
            board = scan_board(skip_noted=("--all" not in sys.argv))
            if show_context:
                board["profile_context"] = load_profile_context()
            print(json.dumps(board, ensure_ascii=False, indent=indent))
        else:
            # 传统模式：只返回 @claude 任务
            tasks = poll(only_pending=("--all" not in sys.argv))
            if show_context:
                profile = load_profile_context()
                output = {
                    "profile_context": profile,
                    "tasks": tasks,
                }
                print(json.dumps(output, ensure_ascii=False, indent=indent))
            else:
                print(json.dumps(tasks, ensure_ascii=False, indent=indent))
    except Exception as e:
        print(f"[poll_tasks] 异常: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
