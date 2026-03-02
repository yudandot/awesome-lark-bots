# -*- coding: utf-8 -*-
"""
creative/asset_tracker.py — 素材需求管理（多维表格版）

维护素材执行需求的全生命周期：
- 一张飞书多维表格，结构化字段（单选状态、链接等）
- 提交需求时写入记录，对接人直接在多维表格上操作
- 月度统计通过日期筛选实现，无需额外 tab
- 与 assistant 项目管理表轻量同步

存储路径：data/creative_assets.json
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_CONFIG_PATH = str(Path(__file__).resolve().parent.parent / "data" / "creative_assets.json")
_lock = threading.Lock()

ASSET_TABLE_FIELDS = [
    {"field_name": "需求编号", "type": 1},
    {"field_name": "品牌", "type": 1},
    {"field_name": "创意概念", "type": 1},
    {"field_name": "素材类型", "type": 3, "property": {"options": [
        {"name": "视频"}, {"name": "图片"}, {"name": "动图"}, {"name": "其他"},
    ]}},
    {"field_name": "渠道", "type": 1},
    {"field_name": "执行方", "type": 1},
    {"field_name": "预算", "type": 1},
    {"field_name": "截止日期", "type": 1},
    {"field_name": "状态", "type": 3, "property": {"options": [
        {"name": "待分配"}, {"name": "进行中"}, {"name": "待审核"},
        {"name": "已完成"}, {"name": "已取消"},
    ]}},
    {"field_name": "Brief链接", "type": 15},
    {"field_name": "提交人", "type": 1},
    {"field_name": "提交日期", "type": 1},
]


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


def _next_id() -> str:
    """生成下一个需求编号，如 CR-001。"""
    with _lock:
        cfg = _load_config()
        seq = cfg.get("next_seq", 1)
        cfg["next_seq"] = seq + 1
        _save_config(cfg)
    return f"CR-{seq:03d}"


def _month_key(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now()).strftime("%Y-%m")


# ── 多维表格初始化 ────────────────────────────────────────────

def init_master_table(owner_open_id: Optional[str] = None) -> Tuple[bool, str]:
    """创建素材需求管理多维表格（首次使用时自动调用）。"""
    from core.feishu_client import create_bitable, create_bitable_table

    with _lock:
        cfg = _load_config()
        if cfg.get("app_token") and cfg.get("table_id"):
            return True, cfg.get("url", "")

    ok, result = create_bitable("📋 素材需求管理")
    if not ok:
        return False, result.get("error", "创建多维表格失败")

    app_token = result["app_token"]
    app_url = result["url"]

    tok, table_id = create_bitable_table(
        app_token, "素材需求", ASSET_TABLE_FIELDS, default_view_name="总表",
    )
    if not tok:
        table_id = result.get("default_table_id", "")
        if not table_id:
            return False, f"创建数据表失败: {table_id}"

    with _lock:
        cfg = _load_config()
        cfg.update({
            "app_token": app_token,
            "table_id": table_id,
            "url": app_url,
            "next_seq": cfg.get("next_seq", 1),
        })
        _save_config(cfg)
    return True, app_url


# ── 提交需求 ──────────────────────────────────────────────────

def submit_asset_request(
    info: Dict[str, str],
    brief_url: str = "",
    owner_open_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """提交一条素材需求到多维表格。返回 (ok, req_id_or_error)。

    info keys: brand, concept, asset_type, channel, executor, budget, deadline, contact, submitter
    """
    from core.feishu_client import add_bitable_record

    cfg = _load_config()
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")

    if not app_token or not table_id:
        ok, msg = init_master_table(owner_open_id)
        if not ok:
            return False, f"初始化管理表失败: {msg}"
        cfg = _load_config()
        app_token = cfg["app_token"]
        table_id = cfg["table_id"]

    req_id = _next_id()
    now = datetime.now()

    asset_type = info.get("asset_type", "其他")
    valid_types = {"视频", "图片", "动图", "其他"}
    if asset_type not in valid_types:
        asset_type = "其他"

    fields: Dict[str, Any] = {
        "需求编号": req_id,
        "品牌": info.get("brand", "待确认"),
        "创意概念": info.get("concept", ""),
        "素材类型": asset_type,
        "渠道": info.get("channel", "待确认"),
        "执行方": info.get("executor", "待确认"),
        "预算": info.get("budget", "待确认"),
        "截止日期": info.get("deadline", "待确认"),
        "状态": "待分配",
        "提交人": info.get("submitter", ""),
        "提交日期": now.strftime("%Y-%m-%d"),
    }
    if brief_url:
        fields["Brief链接"] = {"link": brief_url, "text": "查看Brief"}

    ok, rid_or_err = add_bitable_record(app_token, table_id, fields)
    if not ok:
        return False, f"添加记录失败: {rid_or_err}"

    return True, req_id


# ── 月度统计 ──────────────────────────────────────────────────

def get_monthly_stats(month: Optional[str] = None) -> Dict[str, Any]:
    """获取当月（或指定月）素材需求统计。"""
    from core.feishu_client import list_bitable_records

    mk = month or _month_key()
    cfg = _load_config()
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")

    if not app_token or not table_id:
        return {"total": 0, "by_status": {}, "month": mk}

    ok, records = list_bitable_records(app_token, table_id)
    if not ok:
        return {"total": 0, "by_status": {}, "month": mk}

    by_status: Dict[str, int] = {}
    for rec in records:
        f = rec.get("fields", {})
        date_str = str(f.get("提交日期", ""))
        if date_str.startswith(mk):
            status = f.get("状态", "未知")
            if isinstance(status, list):
                status = status[0] if status else "未知"
            by_status[status] = by_status.get(status, 0) + 1

    return {"total": sum(by_status.values()), "by_status": by_status, "month": mk}


def get_management_table_url() -> str:
    """获取素材需求管理表的 URL。"""
    return _load_config().get("url", "")


# ── 与 assistant 项目表同步 ───────────────────────────────────

def sync_to_assistant(info: Dict[str, str], brief_url: str = "") -> Tuple[bool, str]:
    """将素材需求同步到 assistant 项目管理中心（Bitable 任务表）。"""
    try:
        from memo.bitable_hub import ensure_hub, add_task

        ensure_hub()

        concept = info.get("concept", "素材需求")
        brand = info.get("brand", "")
        project = brand or "素材需求"

        stats = get_monthly_stats()
        total = stats["total"]
        completed = stats["by_status"].get("已完成", 0)
        summary = f"本月素材需求 {total} 条"
        if total > 0:
            summary += f"，已完成 {completed} 条（{completed * 100 // total}%）"

        note = summary
        if brief_url:
            note += f"\nBrief: {brief_url}"
        if info.get("budget"):
            note += f"\n预估预算: {info['budget']}"

        ok, rid = add_task(
            project=project,
            task=f"素材制作：{concept[:50]}",
            source="creative bot",
            assignee=info.get("executor", ""),
            status="待开始",
            due=info.get("deadline", ""),
            note=note,
        )

        return ok, rid
    except Exception as e:
        return False, f"同步失败: {e}"
