# -*- coding: utf-8 -*-
"""
memo/bitable_hub.py — 项目管理中心（多维表格）

一个飞书 Bitable 应用，包含 6 张数据表：
  1. 项目        — 项目注册
  2. 任务        — 各项目的任务/议题
  3. 资料库      — 飞书妙记链接、文档、参考资料
  4. 花费记录    — 所有收支明细
  5. 预算        — 项目预算项 + 实际花费累计
  6. KPI追踪     — 项目目标与进度

多租户：按 team_code 隔离，每个团队拥有独立 Bitable 应用。
team_code="" 使用 "_default" 分区（个人模式）。

持久化配置：data/bitable_hub.json
"""
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CONFIG_PATH = str(Path(__file__).resolve().parent.parent / "data" / "bitable_hub.json")
_lock = threading.Lock()
_DEFAULT_KEY = "_default"


def _log(msg: str) -> None:
    print(f"[BitableHub] {msg}", file=sys.stderr, flush=True)


# ── 配置持久化 ────────────────────────────────────────────────

def _load_config() -> Dict[str, Any]:
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_config(cfg: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _team_key(team_code: str) -> str:
    return team_code.strip() if team_code and team_code.strip() else _DEFAULT_KEY


def _team_cfg(team_code: str = "") -> Dict[str, Any]:
    """获取指定团队的配置分区。"""
    cfg = _load_config()
    key = _team_key(team_code)
    # 兼容旧格式：如果顶层有 app_token 说明是迁移前的平坦结构
    if "app_token" in cfg and key == _DEFAULT_KEY:
        return cfg
    return cfg.get(key, {})


def _save_team_cfg(team_code: str, team_data: Dict[str, Any]) -> None:
    """保存指定团队的配置分区。"""
    key = _team_key(team_code)
    with _lock:
        cfg = _load_config()
        # 迁移旧格式
        if "app_token" in cfg and key == _DEFAULT_KEY:
            old = {k: v for k, v in cfg.items()}
            cfg = {_DEFAULT_KEY: old}
        elif "app_token" in cfg:
            old = {k: v for k, v in cfg.items()}
            cfg = {_DEFAULT_KEY: old}
        cfg[key] = team_data
        _save_config(cfg)


# ── 表定义 ────────────────────────────────────────────────────

_CATEGORY_OPTIONS = [
    {"name": "人力"}, {"name": "营销"}, {"name": "设计"},
    {"name": "技术"}, {"name": "办公"}, {"name": "差旅"},
    {"name": "餐饮"}, {"name": "素材"}, {"name": "其他"},
]

TABLE_DEFS: Dict[str, Dict[str, Any]] = {
    "projects": {
        "name": "项目",
        "view": "全部项目",
        "fields": [
            {"field_name": "项目名称", "type": 1},
            {"field_name": "状态", "type": 3, "property": {"options": [
                {"name": "进行中"}, {"name": "已完成"},
                {"name": "暂停"}, {"name": "已取消"},
            ]}},
            {"field_name": "负责人", "type": 1},
            {"field_name": "总预算", "type": 1},
            {"field_name": "创建日期", "type": 1},
            {"field_name": "备注", "type": 1},
        ],
    },
    "tasks": {
        "name": "任务",
        "view": "全部任务",
        "fields": [
            {"field_name": "任务", "type": 1},
            {"field_name": "项目", "type": 1},
            {"field_name": "来源", "type": 1},
            {"field_name": "负责人", "type": 1},
            {"field_name": "状态", "type": 3, "property": {"options": [
                {"name": "待开始"}, {"name": "进行中"},
                {"name": "已完成"}, {"name": "已取消"},
            ]}},
            {"field_name": "优先级", "type": 3, "property": {"options": [
                {"name": "高"}, {"name": "中"}, {"name": "低"},
            ]}},
            {"field_name": "截止日期", "type": 1},
            {"field_name": "备注", "type": 1},
        ],
    },
    "resources": {
        "name": "资料库",
        "view": "全部资料",
        "fields": [
            {"field_name": "资料名称", "type": 1},
            {"field_name": "项目", "type": 1},
            {"field_name": "类型", "type": 3, "property": {"options": [
                {"name": "飞书妙记"}, {"name": "文档"},
                {"name": "链接"}, {"name": "其他"},
            ]}},
            {"field_name": "链接", "type": 15},
            {"field_name": "来源", "type": 1},
            {"field_name": "添加日期", "type": 1},
            {"field_name": "备注", "type": 1},
        ],
    },
    "expenses": {
        "name": "花费记录",
        "view": "全部花费",
        "fields": [
            {"field_name": "日期", "type": 1},
            {"field_name": "类别", "type": 3, "property": {"options": _CATEGORY_OPTIONS}},
            {"field_name": "项目", "type": 1},
            {"field_name": "描述", "type": 1},
            {"field_name": "金额", "type": 2},
            {"field_name": "收/支", "type": 3, "property": {"options": [
                {"name": "支出"}, {"name": "收入"},
            ]}},
            {"field_name": "付款方式", "type": 1},
            {"field_name": "备注", "type": 1},
        ],
    },
    "budgets": {
        "name": "预算",
        "view": "全部预算",
        "fields": [
            {"field_name": "预算项", "type": 1},
            {"field_name": "项目", "type": 1},
            {"field_name": "类别", "type": 3, "property": {"options": _CATEGORY_OPTIONS}},
            {"field_name": "预算金额", "type": 2},
            {"field_name": "实际花费", "type": 2},
            {"field_name": "剩余", "type": 1},
            {"field_name": "使用率", "type": 1},
            {"field_name": "备注", "type": 1},
        ],
    },
    "kpis": {
        "name": "KPI追踪",
        "view": "全部KPI",
        "fields": [
            {"field_name": "KPI名称", "type": 1},
            {"field_name": "项目", "type": 1},
            {"field_name": "目标值", "type": 1},
            {"field_name": "当前值", "type": 1},
            {"field_name": "单位", "type": 1},
            {"field_name": "进度", "type": 1},
            {"field_name": "截止日期", "type": 1},
            {"field_name": "状态", "type": 3, "property": {"options": [
                {"name": "进行中"}, {"name": "已完成"},
                {"name": "已取消"}, {"name": "延期"},
            ]}},
        ],
    },
}


# ── Hub 初始化 ────────────────────────────────────────────────

def ensure_hub(team_code: str = "") -> Tuple[bool, str]:
    """确保项目管理中心 Bitable 已创建。返回 (ok, url_or_error)。"""
    from core.feishu_client import create_bitable, create_bitable_table

    tcfg = _team_cfg(team_code)
    if tcfg.get("app_token") and tcfg.get("tables"):
        if len(tcfg["tables"]) >= len(TABLE_DEFS):
            return True, tcfg.get("url", "")

    key = _team_key(team_code)
    suffix = f" ({key})" if key != _DEFAULT_KEY else ""
    ok, result = create_bitable(f"📊 项目管理中心{suffix}")
    if not ok:
        err = result.get("error", "创建失败") if isinstance(result, dict) else str(result)
        _log(f"创建 Bitable 失败: {err}")
        return False, err

    app_token = result["app_token"]
    url = result["url"]
    tables: Dict[str, str] = {}

    for tkey, defn in TABLE_DEFS.items():
        tok, tid = create_bitable_table(
            app_token, defn["name"], defn["fields"],
            default_view_name=defn["view"],
        )
        if tok:
            tables[tkey] = tid
            _log(f"  创建表 {defn['name']} -> {tid}")
        else:
            _log(f"  创建表 {defn['name']} 失败: {tid}")

    team_data = {"app_token": app_token, "url": url, "tables": tables}
    _save_team_cfg(team_code, team_data)

    _log(f"项目管理中心已创建: {url} ({len(tables)} 张表) team={key}")
    return True, url


def get_hub_url(team_code: str = "") -> str:
    return _team_cfg(team_code).get("url", "")


def _table_id(key: str, team_code: str = "") -> Tuple[str, str]:
    """返回 (app_token, table_id)，任一为空表示未初始化。"""
    tcfg = _team_cfg(team_code)
    return tcfg.get("app_token", ""), (tcfg.get("tables") or {}).get(key, "")


def _safe_write(fn_name: str, fn, *args, **kwargs) -> Tuple[bool, str]:
    """包装 Bitable 写入，失败时 log 但不抛异常。"""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        _log(f"{fn_name} 异常: {e}")
        return False, str(e)


# ── 项目表 ────────────────────────────────────────────────────

def add_project(
    name: str,
    status: str = "进行中",
    owner: str = "",
    total_budget: str = "",
    note: str = "",
    team_code: str = "",
) -> Tuple[bool, str]:
    from core.feishu_client import add_bitable_record
    app, tid = _table_id("projects", team_code)
    if not app or not tid:
        ok, _ = ensure_hub(team_code)
        if not ok:
            return False, "Hub 未初始化"
        app, tid = _table_id("projects", team_code)
    fields = {
        "项目名称": name,
        "状态": status,
        "负责人": owner,
        "总预算": total_budget,
        "创建日期": datetime.now().strftime("%Y-%m-%d"),
        "备注": note,
    }
    return _safe_write("add_project", add_bitable_record, app, tid, fields)


# ── 任务表 ────────────────────────────────────────────────────

def add_task(
    project: str,
    task: str,
    source: str = "手动添加",
    assignee: str = "",
    status: str = "待开始",
    priority: str = "",
    due: str = "",
    note: str = "",
    team_code: str = "",
) -> Tuple[bool, str]:
    from core.feishu_client import add_bitable_record
    app, tid = _table_id("tasks", team_code)
    if not app or not tid:
        return False, "任务表未初始化"
    fields: Dict[str, Any] = {
        "任务": task,
        "项目": project,
        "来源": source,
        "负责人": assignee,
        "状态": status,
        "备注": note,
    }
    if priority:
        fields["优先级"] = priority
    if due:
        fields["截止日期"] = due
    return _safe_write("add_task", add_bitable_record, app, tid, fields)


# ── 资料库表 ──────────────────────────────────────────────────

def add_resource(
    project: str,
    name: str,
    res_type: str = "其他",
    link: str = "",
    source: str = "自动记录",
    note: str = "",
    team_code: str = "",
) -> Tuple[bool, str]:
    from core.feishu_client import add_bitable_record
    app, tid = _table_id("resources", team_code)
    if not app or not tid:
        return False, "资料库表未初始化"
    valid_types = {"飞书妙记", "文档", "链接", "其他"}
    if res_type not in valid_types:
        res_type = "其他"
    fields: Dict[str, Any] = {
        "资料名称": name,
        "项目": project,
        "类型": res_type,
        "来源": source,
        "添加日期": datetime.now().strftime("%Y-%m-%d"),
        "备注": note,
    }
    if link:
        fields["链接"] = {"link": link, "text": name}
    return _safe_write("add_resource", add_bitable_record, app, tid, fields)


# ── 花费记录表 ────────────────────────────────────────────────

def add_expense_record(
    date: str,
    category: str,
    project: str,
    description: str,
    amount: float,
    expense_type: str = "支出",
    payment: str = "",
    note: str = "",
    team_code: str = "",
) -> Tuple[bool, str]:
    """写入花费记录，并自动累加到预算表对应行。"""
    from core.feishu_client import add_bitable_record
    app, tid = _table_id("expenses", team_code)
    if not app or not tid:
        return False, "花费记录表未初始化"
    fields: Dict[str, Any] = {
        "日期": date,
        "类别": category,
        "项目": project,
        "描述": description,
        "金额": round(float(amount), 2),
        "收/支": expense_type,
        "付款方式": payment,
        "备注": note,
    }
    ok, rid = _safe_write("add_expense_record", add_bitable_record, app, tid, fields)
    if ok and expense_type == "支出" and project:
        _update_budget_actual(project, category, float(amount), team_code)
    return ok, rid


def _update_budget_actual(project: str, category: str, amount: float, team_code: str = "") -> None:
    """在预算表中查找 项目+类别 匹配的行，累加实际花费并重算剩余/使用率。"""
    from core.feishu_client import list_bitable_records, update_bitable_record

    app, tid = _table_id("budgets", team_code)
    if not app or not tid:
        return

    try:
        ok, records = list_bitable_records(app, tid)
        if not ok:
            return

        proj_lower = project.strip().lower()
        cat_lower = category.strip().lower()

        for rec in records:
            f = rec.get("fields", {})
            r_proj = str(f.get("项目", "")).strip().lower()
            r_cat = str(f.get("类别", "")).strip().lower()
            if r_proj == proj_lower and r_cat == cat_lower:
                record_id = rec.get("record_id", "")
                if not record_id:
                    continue
                old_actual = float(f.get("实际花费", 0) or 0)
                budget_amt = float(f.get("预算金额", 0) or 0)
                new_actual = round(old_actual + amount, 2)
                remaining = round(budget_amt - new_actual, 2)
                usage = f"{new_actual / budget_amt * 100:.0f}%" if budget_amt > 0 else "-"
                update_bitable_record(app, tid, record_id, {
                    "实际花费": new_actual,
                    "剩余": f"¥{remaining:,.0f}",
                    "使用率": usage,
                })
                _log(f"预算累加: {project}/{category} +{amount} -> 实际{new_actual}")
                return
    except Exception as e:
        _log(f"预算累加异常: {e}")


# ── 预算表 ────────────────────────────────────────────────────

def add_budget_item(
    project: str,
    name: str,
    category: str,
    amount: float,
    note: str = "",
    team_code: str = "",
) -> Tuple[bool, str]:
    from core.feishu_client import add_bitable_record
    app, tid = _table_id("budgets", team_code)
    if not app or not tid:
        return False, "预算表未初始化"
    fields: Dict[str, Any] = {
        "预算项": name,
        "项目": project,
        "类别": category,
        "预算金额": round(float(amount), 2),
        "实际花费": 0,
        "剩余": f"¥{amount:,.0f}",
        "使用率": "0%",
        "备注": note,
    }
    return _safe_write("add_budget_item", add_bitable_record, app, tid, fields)


# ── KPI 追踪表 ────────────────────────────────────────────────

def add_or_update_kpi(
    project: str,
    name: str,
    target: str = "",
    current: str = "",
    unit: str = "",
    deadline: str = "",
    status: str = "进行中",
    team_code: str = "",
) -> Tuple[bool, str]:
    """新增或更新 KPI 记录。按 项目+KPI名称 查找已有行。"""
    from core.feishu_client import (
        add_bitable_record, list_bitable_records, update_bitable_record,
    )

    app, tid = _table_id("kpis", team_code)
    if not app or not tid:
        return False, "KPI表未初始化"

    try:
        pct = "-"
        try:
            t_val = float(target) if target else 0
            c_val = float(current) if current else 0
            if t_val > 0:
                pct = f"{c_val / t_val * 100:.0f}%"
        except (ValueError, ZeroDivisionError):
            pass
    except Exception:
        pct = "-"

    ok, records = list_bitable_records(app, tid)
    if ok:
        proj_lower = project.strip().lower()
        name_lower = name.strip().lower()
        for rec in records:
            f = rec.get("fields", {})
            if (str(f.get("项目", "")).strip().lower() == proj_lower
                    and str(f.get("KPI名称", "")).strip().lower() == name_lower):
                record_id = rec.get("record_id", "")
                if record_id:
                    updates: Dict[str, Any] = {"进度": pct}
                    if current:
                        updates["当前值"] = current
                    if target:
                        updates["目标值"] = target
                    if status:
                        updates["状态"] = status
                    return _safe_write(
                        "update_kpi", update_bitable_record, app, tid, record_id, updates,
                    )

    fields: Dict[str, Any] = {
        "KPI名称": name,
        "项目": project,
        "目标值": target,
        "当前值": current or "0",
        "单位": unit,
        "进度": pct,
        "截止日期": deadline,
        "状态": status,
    }
    return _safe_write("add_kpi", add_bitable_record, app, tid, fields)
