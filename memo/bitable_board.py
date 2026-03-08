# -*- coding: utf-8 -*-
"""
memo/bitable_board.py — 备忘看板（独立多维表格）

一个飞书 Bitable 应用，包含一张数据表，用于展示线程备忘的分区看板。
支持智能 upsert 刷新（按 memo_id 匹配：有则更新、无则新增、多余删除）
和增量追加（新建备忘时实时写入）。

v2: 新增 memo_id / 执行者 / Claude备注 字段，支持 @claude 任务标记。
    已有看板会自动迁移（补全缺失字段）。

持久化配置：data/bitable_board.json
"""
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CONFIG_PATH = str(Path(__file__).resolve().parent.parent / "data" / "bitable_board.json")
_lock = threading.Lock()
_migrated = False  # 单次运行只迁移一次


def _log(msg: str) -> None:
    print(f"[BitableBoard] {msg}", file=sys.stderr, flush=True)


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


# ── 表定义 ────────────────────────────────────────────────────

TABLE_DEF = {
    "name": "看板",
    "view": "全部备忘",
    "fields": [
        {"field_name": "memo_id", "type": 1},
        {"field_name": "线程", "type": 1},
        {"field_name": "内容", "type": 1},
        {"field_name": "状态", "type": 3, "property": {"options": [
            {"name": "进行中"}, {"name": "待跟进"}, {"name": "已完成"},
        ]}},
        {"field_name": "创建时间", "type": 1},
        {"field_name": "分区", "type": 3, "property": {"options": [
            {"name": "今日新增"}, {"name": "本周进行中"},
            {"name": "等待跟进"}, {"name": "已完成"},
        ]}},
        {"field_name": "执行者", "type": 3, "property": {"options": [
            {"name": "Claude"}, {"name": "人工"},
        ]}},
        {"field_name": "Claude备注", "type": 1},
    ],
}

_STATUS_MAP = {
    "🆕 进行中": "进行中",
    "⬜ 进行中": "进行中",
    "⏳ 待跟进": "待跟进",
    "✅ 已完成": "已完成",
}

# 需要迁移的字段（旧看板可能缺少的）
_MIGRATE_FIELDS = [
    {"field_name": "memo_id", "type": 1},
    {"field_name": "执行者", "type": 3, "property": {"options": [
        {"name": "Claude"}, {"name": "人工"},
    ]}},
    {"field_name": "Claude备注", "type": 1},
]


# ── 字段迁移 ────────────────────────────────────────────────

def _migrate_fields_if_needed(app_token: str, table_id: str) -> None:
    """检查已有看板是否缺少新字段，缺的就补上。"""
    global _migrated
    if _migrated:
        return
    _migrated = True

    try:
        from core.feishu_client import list_bitable_fields, add_bitable_field

        ok, fields = list_bitable_fields(app_token, table_id)
        if not ok:
            _log("迁移检查：无法获取字段列表，跳过")
            return

        existing_names = {f.get("field_name", "") for f in fields}
        for field_def in _MIGRATE_FIELDS:
            name = field_def["field_name"]
            if name not in existing_names:
                prop = field_def.get("property")
                ok_add, result = add_bitable_field(
                    app_token, table_id, name,
                    field_type=field_def["type"],
                    property=prop,
                )
                if ok_add:
                    _log(f"迁移成功：已添加字段「{name}」")
                else:
                    _log(f"迁移失败：添加字段「{name}」— {result}")
    except Exception as e:
        _log(f"字段迁移异常: {e}")


# ── 初始化 ────────────────────────────────────────────────────

def ensure_board() -> Tuple[bool, str]:
    """确保备忘看板 Bitable 已创建，并迁移缺失字段。返回 (ok, url_or_error)。"""
    from core.feishu_client import create_bitable, create_bitable_table

    with _lock:
        cfg = _load_config()
        if cfg.get("app_token") and cfg.get("table_id"):
            _migrate_fields_if_needed(cfg["app_token"], cfg["table_id"])
            return True, cfg.get("url", "")

    ok, result = create_bitable("📋 备忘看板")
    if not ok:
        err = result.get("error", "创建失败") if isinstance(result, dict) else str(result)
        _log(f"创建 Bitable 失败: {err}")
        return False, err

    app_token = result["app_token"]
    url = result["url"]

    tok, tid = create_bitable_table(
        app_token, TABLE_DEF["name"], TABLE_DEF["fields"],
        default_view_name=TABLE_DEF["view"],
    )
    if not tok:
        _log(f"创建看板表失败: {tid}")
        return False, f"创建看板表失败: {tid}"

    with _lock:
        cfg = _load_config()
        cfg.update({"app_token": app_token, "table_id": tid, "url": url})
        _save_config(cfg)

    _log(f"备忘看板已创建: {url}")
    return True, url


def get_board_url() -> str:
    return _load_config().get("url", "")


def _get_ids() -> Tuple[str, str]:
    """返回 (app_token, table_id)。"""
    cfg = _load_config()
    return cfg.get("app_token", ""), cfg.get("table_id", "")


def _assignee_display(assignee: str) -> str:
    """将内部 assignee 值转换为 Bitable 单选显示值。"""
    if assignee == "claude":
        return "Claude"
    if assignee:
        return "人工"
    return ""


def _row_to_fields(row: list) -> dict:
    """将 export_board_data 的一行转换为 Bitable fields dict。

    row 格式: [memo_id, 线程, 内容, 状态, 创建时间, 分区, 执行者]
    """
    raw_status = row[3] if len(row) > 3 else "进行中"
    status = _STATUS_MAP.get(raw_status, "进行中")
    assignee = row[6] if len(row) > 6 else ""
    fields = {
        "memo_id": row[0] if row else "",
        "线程": row[1] if len(row) > 1 else "",
        "内容": row[2] if len(row) > 2 else "",
        "状态": status,
        "创建时间": row[4] if len(row) > 4 else "",
        "分区": row[5] if len(row) > 5 else "今日新增",
    }
    display = _assignee_display(assignee)
    if display:
        fields["执行者"] = display
    return fields


# ── 智能刷新（upsert）────────────────────────────────────────

def refresh_board(
    user_open_id: str = "",
    thread: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, int]]:
    """智能刷新看板：按 memo_id 匹配，有则更新、无则新增、多余删除。

    不会覆盖 Claude备注 字段（由 Claude Code 单独管理）。

    Returns: (ok, url_or_error, stats)
    """
    from memo.store import export_board_data
    from core.feishu_client import (
        add_bitable_record,
        list_bitable_records,
        update_bitable_record,
        batch_delete_bitable_records,
    )

    ok, url = ensure_board()
    if not ok:
        return False, url, {}

    app, tid = _get_ids()
    if not app or not tid:
        return False, "看板未初始化", {}

    # ① 获取本地最新数据
    headers, rows, stats = export_board_data(
        user_open_id=user_open_id, thread=thread,
    )

    # ② 获取 Bitable 现有记录，建立 memo_id → record_id 映射
    ok_list, existing = list_bitable_records(app, tid)
    existing_map: Dict[str, str] = {}  # memo_id → record_id
    if ok_list and existing:
        for rec in existing:
            rec_fields = rec.get("fields") or {}
            mid = rec_fields.get("memo_id") or ""
            rid = rec.get("record_id") or ""
            if mid and rid:
                existing_map[mid] = rid

    # ③ Upsert：遍历本地数据
    seen_memo_ids = set()
    updated = 0
    created = 0
    for row in rows:
        memo_id = row[0] if row else ""
        fields = _row_to_fields(row)

        if memo_id and memo_id in existing_map:
            # 已有记录 → 更新（不覆盖 Claude备注）
            record_id = existing_map[memo_id]
            update_bitable_record(app, tid, record_id, fields)
            seen_memo_ids.add(memo_id)
            updated += 1
        else:
            # 新记录 → 创建
            add_bitable_record(app, tid, fields)
            if memo_id:
                seen_memo_ids.add(memo_id)
            created += 1

    # ④ 清理：删除本地已不存在的记录（但保留无 memo_id 的旧记录）
    stale_record_ids = [
        rid for mid, rid in existing_map.items()
        if mid and mid not in seen_memo_ids
    ]
    deleted = 0
    if stale_record_ids:
        batch_delete_bitable_records(app, tid, stale_record_ids)
        deleted = len(stale_record_ids)

    _log(f"看板刷新完成: 更新{updated} 新增{created} 删除{deleted} (共{len(rows)}条)")
    return True, url, stats


# ── 追加单条 ────────────────────────────────────────────────

def append_board_record(
    thread: str,
    content: str,
    status: str = "进行中",
    created: str = "",
    partition: str = "今日新增",
    assignee: str = "",
    memo_id: str = "",
) -> Tuple[bool, str]:
    """追加一条看板记录（给自动追加用）。"""
    from core.feishu_client import add_bitable_record

    app, tid = _get_ids()
    if not app or not tid:
        return False, "看板未初始化"

    clean_status = _STATUS_MAP.get(status, status)
    if clean_status not in ("进行中", "待跟进", "已完成"):
        clean_status = "进行中"

    fields = {
        "线程": thread or "(未分类)",
        "内容": content[:120],
        "状态": clean_status,
        "创建时间": created,
        "分区": partition,
    }
    if memo_id:
        fields["memo_id"] = memo_id
    display = _assignee_display(assignee)
    if display:
        fields["执行者"] = display

    try:
        return add_bitable_record(app, tid, fields)
    except Exception as e:
        _log(f"追加看板记录异常: {e}")
        return False, str(e)
