# -*- coding: utf-8 -*-
"""
本地备忘存储：JSON 文件，支持分类（日常/灵感/要事）、按用户隔离。
存储路径：项目根目录 data/memos.json（可通过 MEMO_STORE_PATH 覆盖）。
"""
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

MEMO_CATEGORIES = {"日常": "daily", "灵感": "creative", "要事": "project"}
MEMO_CATEGORY_KEYS = list(MEMO_CATEGORIES.values())
MEMO_CATEGORY_DISPLAY = {v: k for k, v in MEMO_CATEGORIES.items()}

_DEFAULT_PATH = str(Path(__file__).resolve().parent.parent / "data" / "memos.json")
_lock = threading.Lock()


def _path() -> str:
    return (os.environ.get("MEMO_STORE_PATH") or "").strip() or _DEFAULT_PATH


def _load_all_unlocked() -> List[Dict[str, Any]]:
    """读取全部备忘（调用方需持有 _lock）。"""
    p = _path()
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_all_unlocked(items: List[Dict[str, Any]]) -> None:
    """写入全部备忘（调用方需持有 _lock）。"""
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def _load_all() -> List[Dict[str, Any]]:
    with _lock:
        return _load_all_unlocked()


def _save_all(items: List[Dict[str, Any]]) -> None:
    with _lock:
        _save_all_unlocked(items)


def _normalize_category(cat: Optional[str]) -> str:
    if not cat or not str(cat).strip():
        return ""
    c = str(cat).strip()
    if c in MEMO_CATEGORIES:
        return MEMO_CATEGORIES[c]
    if c in MEMO_CATEGORY_DISPLAY:
        return c
    return ""


def add_memo(
    content: str,
    user_open_id: Optional[str] = None,
    reminder_date: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    cat_key = _normalize_category(category)
    memo = {
        "id": str(uuid.uuid4()),
        "content": content.strip(),
        "created_at": now,
        "user_open_id": user_open_id or "",
        "reminder_date": reminder_date or "",
        "category": cat_key or "",
    }
    with _lock:
        items = _load_all_unlocked()
        items.append(memo)
        _save_all_unlocked(items)
    return memo["id"]


def list_memos(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user_open_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    items = _load_all()
    if user_open_id:
        items = [m for m in items if m.get("user_open_id") == user_open_id]
    cat_key = _normalize_category(category)
    if cat_key:
        items = [m for m in items if (m.get("category") or "") == cat_key]
    if date_from or date_to:
        def in_range(m: dict) -> bool:
            d = (m.get("reminder_date") or m.get("created_at", "")[:10]) or "0000-00-00"
            if date_from and d < date_from:
                return False
            if date_to and d > date_to:
                return False
            return True
        items = [m for m in items if in_range(m)]
    items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return items[:limit]


def delete_memo_by_index(index_one_based: int, user_open_id: Optional[str] = None) -> tuple[bool, str]:
    with _lock:
        all_items = _load_all_unlocked()
        items = list(all_items)
        if user_open_id:
            items = [m for m in items if m.get("user_open_id") == user_open_id]
        items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        if index_one_based < 1 or index_one_based > len(items):
            return False, f"序号需在 1～{len(items)} 之间，当前共 {len(items)} 条备忘。"
        to_remove = items[index_one_based - 1]
        memo_id = to_remove.get("id")
        content_preview = (to_remove.get("content") or "")[:20]
        all_items = [m for m in all_items if m.get("id") != memo_id]
        _save_all_unlocked(all_items)
    return True, f"已清除第 {index_one_based} 条备忘：{content_preview}{'…' if len(to_remove.get('content') or '') > 20 else ''}"


def set_memo_category_by_index(
    index_one_based: int,
    category: str,
    user_open_id: Optional[str] = None,
) -> tuple[bool, str]:
    cat_key = _normalize_category(category)
    if not cat_key:
        return False, "分类需为：日常、灵感、要事 之一。"
    with _lock:
        all_items = _load_all_unlocked()
        items = list(all_items)
        if user_open_id:
            items = [m for m in items if m.get("user_open_id") == user_open_id]
        items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        if index_one_based < 1 or index_one_based > len(items):
            return False, f"序号需在 1～{len(items)} 之间，当前共 {len(items)} 条备忘。"
        target = items[index_one_based - 1]
        memo_id = target.get("id")
        display = MEMO_CATEGORY_DISPLAY.get(cat_key, category)
        for m in all_items:
            if m.get("id") == memo_id:
                m["category"] = cat_key
                break
        _save_all_unlocked(all_items)
    content_preview = (target.get("content") or "")[:15]
    return True, f"已把第 {index_one_based} 条标为「{display}」：{content_preview}{'…' if len(target.get('content') or '') > 15 else ''}"
