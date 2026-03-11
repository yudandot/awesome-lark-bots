# -*- coding: utf-8 -*-
"""
memo/bitable_board.py — 备忘看板（独立多维表格）

一个飞书 Bitable 应用，包含一张数据表，用于展示线程备忘的分区看板。
支持智能 upsert 刷新（按 memo_id 匹配：有则更新、无则新增、多余删除）
和增量追加（新建备忘时实时写入）。

v2: 新增 memo_id / 执行者 / Claude备注 字段，支持 @claude 任务标记。
    已有看板会自动迁移（补全缺失字段）。
v3: 新增 搭档反馈 字段，支持用户在 Bitable 里直接给 Claude 反馈。

持久化配置：data/bitable_board.json
"""
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DATA_DIR = str(Path(__file__).resolve().parent.parent / "data")
_CONFIG_PATH = os.path.join(_DATA_DIR, "bitable_board.json")
_SYNCED_IDS_PATH = os.path.join(_DATA_DIR, "board_synced_ids.json")
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


# ── 已同步 ID 追踪（防止删了又回来）────────────────────────

def _load_synced_ids() -> set:
    """加载曾经同步到 Bitable 的 memo_id 集合。"""
    if not os.path.exists(_SYNCED_IDS_PATH):
        return set()
    try:
        with open(_SYNCED_IDS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, IOError):
        return set()


def _save_synced_ids(ids: set) -> None:
    os.makedirs(os.path.dirname(_SYNCED_IDS_PATH), exist_ok=True)
    with open(_SYNCED_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f)


def _mark_synced(memo_id: str) -> None:
    """标记一个 memo_id 已同步过（线程安全）。"""
    if not memo_id:
        return
    with _lock:
        ids = _load_synced_ids()
        ids.add(memo_id)
        _save_synced_ids(ids)


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
        {"field_name": "搭档反馈", "type": 1},
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
    {"field_name": "搭档反馈", "type": 1},
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

def _reverse_sync_status(existing_records: list) -> int:
    """反向同步：如果用户在 Bitable 手动改了状态，回写到 memos.json。

    返回同步的条数。
    """
    from memo.store import complete_memo_by_id, uncomplete_memo_by_id

    synced = 0
    for rec in (existing_records or []):
        fields = rec.get("fields") or {}
        memo_id = fields.get("memo_id") or ""
        if not memo_id:
            continue

        bitable_status = fields.get("状态") or ""
        # 单选字段可能返回 str 或 dict
        if isinstance(bitable_status, dict):
            bitable_status = bitable_status.get("value", "") or bitable_status.get("name", "")

        if bitable_status == "已完成":
            if complete_memo_by_id(memo_id):
                _log(f"反向同步: {memo_id[:8]}… → 已完成")
                synced += 1
        elif bitable_status in ("进行中", "待跟进"):
            if uncomplete_memo_by_id(memo_id):
                _log(f"反向同步: {memo_id[:8]}… → 未完成")
                synced += 1

    return synced


def refresh_board(
    user_open_id: str = "",
    thread: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, int]]:
    """刷新看板（以 Bitable 为真相源）。

    流程：
      0. 反向同步 — 用户在 Bitable 手动改的状态回写 memos.json
      1. 获取本地最新数据
      2. Upsert — 已有则更新，新增则创建（但绝不重建被删除的记录）
      ❌ 不再删除 Bitable 记录（以看板为准）

    不会覆盖 Claude备注 / 搭档反馈 字段。

    Returns: (ok, url_or_error, stats)
    """
    from memo.store import export_board_data
    from core.feishu_client import (
        add_bitable_record,
        list_bitable_records,
        update_bitable_record,
    )

    ok, url = ensure_board()
    if not ok:
        return False, url, {}

    app, tid = _get_ids()
    if not app or not tid:
        return False, "看板未初始化", {}

    # ⓪ 获取 Bitable 现有记录
    ok_list, existing = list_bitable_records(app, tid)
    existing_map: Dict[str, str] = {}  # memo_id → record_id
    if ok_list and existing:
        for rec in existing:
            rec_fields = rec.get("fields") or {}
            mid = rec_fields.get("memo_id") or ""
            rid = rec.get("record_id") or ""
            if mid and rid:
                existing_map[mid] = rid

        # 反向同步：用户手动改的状态 → memos.json
        rev_synced = _reverse_sync_status(existing)
        if rev_synced:
            _log(f"反向同步完成: {rev_synced} 条状态变更已写回本地")

    # 加载曾同步过的 memo_id（用于防止删了又回来）
    synced_ids = _load_synced_ids()
    # 当前 Bitable 里有的 memo_id 也算同步过
    synced_ids.update(existing_map.keys())

    # ① 获取本地最新数据（反向同步后的，跳过已完成项）
    headers, rows, stats = export_board_data(
        user_open_id=user_open_id, thread=thread, skip_done=True,
    )

    # ② Upsert：遍历本地数据
    updated = 0
    created = 0
    for row in rows:
        memo_id = row[0] if row else ""
        fields = _row_to_fields(row)

        if memo_id and memo_id in existing_map:
            # 已有记录 → 更新（不覆盖 Claude备注/搭档反馈）
            record_id = existing_map[memo_id]
            update_bitable_record(app, tid, record_id, fields)
            synced_ids.add(memo_id)
            updated += 1
        elif memo_id and memo_id in synced_ids:
            # 曾经同步过但已被从 Bitable 删除 → 不重建（尊重看板删除）
            pass
        else:
            # 全新记录（从未同步过）→ 创建
            add_bitable_record(app, tid, fields)
            if memo_id:
                synced_ids.add(memo_id)
            created += 1

    # ❌ 不再删除 Bitable 记录（以看板为准）

    # 持久化同步记录
    _save_synced_ids(synced_ids)

    _log(f"看板刷新完成: 更新{updated} 新增{created} 跳过已删{len(synced_ids) - len(existing_map) - created}")
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
        ok_add, result = add_bitable_record(app, tid, fields)
        if ok_add and memo_id:
            _mark_synced(memo_id)
        return ok_add, result
    except Exception as e:
        _log(f"追加看板记录异常: {e}")
        return False, str(e)


# ── 单条同步 ─────────────────────────────────────────────────

def mark_board_record_done(memo_id: str) -> bool:
    """按 memo_id 把看板中对应记录标记为已完成。"""
    if not memo_id:
        return False
    from core.feishu_client import list_bitable_records, update_bitable_record

    app, tid = _get_ids()
    if not app or not tid:
        return False

    ok, records = list_bitable_records(app, tid)
    if not ok or not records:
        return False

    for rec in records:
        fields = rec.get("fields") or {}
        if fields.get("memo_id") == memo_id:
            record_id = rec.get("record_id")
            if record_id:
                update_bitable_record(app, tid, record_id, {
                    "状态": "已完成",
                    "分区": "已完成",
                })
                _log(f"看板同步: {memo_id[:8]}… → 已完成")
                return True
    return False


def list_active_board_records(thread: Optional[str] = None) -> List[Dict[str, Any]]:
    """从 Bitable 看板读取未完成的记录（以看板为唯一真相源）。

    返回状态不为「已完成」的记录列表，格式兼容 store.list_memos() 的输出。
    可选按线程筛选。
    """
    from core.feishu_client import list_bitable_records

    app, tid = _get_ids()
    if not app or not tid:
        return []

    ok, records = list_bitable_records(app, tid)
    if not ok or not records:
        return []

    result = []
    for rec in records:
        f = rec.get("fields") or {}
        status = f.get("状态", "")
        if status == "已完成":
            continue

        rec_thread = f.get("线程", "") or ""
        if thread and rec_thread != thread:
            continue

        result.append({
            "id": f.get("memo_id", ""),
            "content": f.get("内容", ""),
            "thread": rec_thread,
            "assignee": (f.get("执行者", "") or "").lower(),
            "done": False,
            "created_at": f.get("创建时间", ""),
            "status": status,
            "claude_note": f.get("Claude备注", ""),
            "partner_feedback": f.get("搭档反馈", ""),
            "record_id": rec.get("record_id", ""),
        })

    # 按创建时间降序
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result


def delete_board_record(memo_id: str) -> bool:
    """按 memo_id 删除看板中对应记录。"""
    if not memo_id:
        return False
    from core.feishu_client import list_bitable_records, batch_delete_bitable_records

    app, tid = _get_ids()
    if not app or not tid:
        return False

    ok, records = list_bitable_records(app, tid)
    if not ok or not records:
        return False

    for rec in records:
        fields = rec.get("fields") or {}
        if fields.get("memo_id") == memo_id:
            record_id = rec.get("record_id")
            if record_id:
                batch_delete_bitable_records(app, tid, [record_id])
                _log(f"看板同步: {memo_id[:8]}… → 已删除")
                return True
    return False
