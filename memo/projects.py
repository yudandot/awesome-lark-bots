# -*- coding: utf-8 -*-
"""
团队项目注册表 — 记录每个项目对应的飞书电子表格信息，支持持续维护。

存储路径：data/projects.json
每个项目：{id, name, spreadsheet_token, sheet_id, url, created_at, created_by}
"""
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_PATH = str(Path(__file__).resolve().parent.parent / "data" / "projects.json")
_lock = threading.Lock()

PROJECT_HEADERS = ["任务/议题", "来源", "负责人", "状态", "优先级", "截止日期", "备注"]


def _normalize_name(name: str) -> str:
    """统一项目名称：去首尾空格、转小写、合并连续空格。"""
    return " ".join(name.strip().lower().split())


def _path() -> str:
    return (os.environ.get("PROJECT_STORE_PATH") or "").strip() or _DEFAULT_PATH


def _load() -> List[Dict[str, Any]]:
    p = _path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def register_project(
    name: str,
    spreadsheet_token: str,
    sheet_id: str,
    url: str,
    created_by: str = "",
    tags: Optional[List[str]] = None,
    source: str = "",
    doc_type: str = "",
    team_code: str = "",
) -> str:
    """注册新项目，返回 project_id。

    新增可选字段：
      tags      — 项目标签列表，如 ["营销", "Q3"]
      source    — 来源标识，如 "planner"
      doc_type  — 文档类型，如 "执行 Brief"
      team_code — 所属团队码（空 = 个人/全局）
    """
    project = {
        "id": str(uuid.uuid4()),
        "name": name.strip(),
        "spreadsheet_token": spreadsheet_token,
        "sheet_id": sheet_id,
        "url": url,
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_by": created_by,
        "team_code": team_code,
    }
    if tags:
        project["tags"] = tags
    if source:
        project["source"] = source
    if doc_type:
        project["doc_type"] = doc_type
    with _lock:
        items = _load()
        items.append(project)
        _save(items)

    try:
        from memo.bitable_hub import add_project as _bt_add_project, get_hub_url
        _bt_add_project(name=name.strip(), owner=created_by, team_code=team_code)
        bitable_url = get_hub_url(team_code=team_code)
        if bitable_url:
            project["bitable_url"] = bitable_url
            with _lock:
                all_items = _load()
                for it in all_items:
                    if it["id"] == project["id"]:
                        it["bitable_url"] = bitable_url
                        break
                _save(all_items)
    except Exception:
        pass

    return project["id"]


def list_projects(team_code: str = "") -> List[Dict[str, Any]]:
    """列出项目。传 team_code 则只返回该团队的项目。"""
    with _lock:
        items = list(_load())
    if team_code:
        items = [p for p in items if p.get("team_code") == team_code]
    return items


def find_project(name: str, team_code: str = "") -> Optional[Dict[str, Any]]:
    """按名称模糊查找项目（归一化后比较）。优先在 team_code 范围内查找。"""
    key = _normalize_name(name)
    with _lock:
        items = _load()
    if team_code:
        scoped = [p for p in items if p.get("team_code") == team_code]
    else:
        scoped = items
    for p in scoped:
        if _normalize_name(p["name"]) == key:
            return p
    for p in scoped:
        if key in _normalize_name(p["name"]):
            return p
    if team_code:
        for p in items:
            if _normalize_name(p["name"]) == key:
                return p
    return None


def delete_project(name: str, team_code: str = "") -> Tuple[bool, str]:
    """按名称删除项目注册（不删飞书表格）。"""
    key = _normalize_name(name)
    with _lock:
        items = _load()
        before = len(items)
        if team_code:
            items = [p for p in items if not (
                _normalize_name(p["name"]) == key and p.get("team_code") == team_code
            )]
        else:
            items = [p for p in items if _normalize_name(p["name"]) != key]
        if len(items) == before:
            return False, f"未找到项目「{name}」"
        _save(items)
    return True, f"已移除项目「{name}」的注册"
