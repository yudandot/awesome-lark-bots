# -*- coding: utf-8 -*-
"""
内容仓库 — 存储、检索、管理所有生成的内容。

所有内容以 JSON 文件持久化在 data/conductor/content/ 下。
支持按状态（草稿/待发/已发/定时）筛选，支持定时发布队列。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from conductor.config import DATA_DIR, log

CONTENT_DIR = DATA_DIR / "content"
CONTENT_DIR.mkdir(parents=True, exist_ok=True)


class ContentStatus:
    DRAFT = "draft"             # 草稿（刚生成）
    READY = "ready"             # 待发布（已审核通过）
    SCHEDULED = "scheduled"     # 定时发布
    PUBLISHED = "published"     # 已发布
    FAILED = "failed"           # 发布失败


@dataclass
class ContentItem:
    """一条可发布的内容。"""
    content_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

    # 内容信息
    title: str = ""
    topic: str = ""
    brand: str = ""
    content_type: str = "short_video"

    # 各平台文案
    platform_copy: dict[str, str] = field(default_factory=dict)
    hashtags: list[str] = field(default_factory=list)

    # 视觉素材
    visual_prompt: str = ""
    visual_prompt_en: str = ""

    # 创意来源
    idea_title: str = ""
    idea_angle: str = ""
    idea_hook: str = ""

    # 生成的素材
    generated_assets: list[str] = field(default_factory=list)

    # 状态
    status: str = ContentStatus.DRAFT
    quality_score: float = 0.0
    quality_feedback: str = ""

    # 发布信息
    target_platforms: list[str] = field(default_factory=list)
    scheduled_at: float = 0.0               # 定时发布时间（unix timestamp）
    published_at: float = 0.0
    publish_urls: dict[str, str] = field(default_factory=dict)  # platform → url
    publish_errors: dict[str, str] = field(default_factory=dict)

    # 关联
    run_id: str = ""                        # Pipeline run ID

    def save(self) -> Path:
        path = CONTENT_DIR / f"{self.content_id}.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    @classmethod
    def load(cls, content_id: str) -> Optional["ContentItem"]:
        path = CONTENT_DIR / f"{content_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            item = cls()
            for k, v in data.items():
                if hasattr(item, k):
                    setattr(item, k, v)
            return item
        except Exception:
            return None


class ContentStore:
    """内容仓库管理器。"""

    def __init__(self):
        self._lock = threading.Lock()

    def save(self, item: ContentItem) -> str:
        """保存内容项，返回 content_id。"""
        with self._lock:
            item.save()
            log.info("内容已保存: %s [%s] %s", item.content_id, item.status, item.title[:40])
            return item.content_id

    def get(self, content_id: str) -> Optional[ContentItem]:
        return ContentItem.load(content_id)

    def list_all(self, status: Optional[str] = None) -> list[ContentItem]:
        """列出所有内容，可按状态筛选。"""
        items = []
        for f in sorted(CONTENT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            item = ContentItem.load(f.stem)
            if item and (status is None or item.status == status):
                items.append(item)
        return items

    def list_drafts(self) -> list[ContentItem]:
        return self.list_all(ContentStatus.DRAFT)

    def list_ready(self) -> list[ContentItem]:
        return self.list_all(ContentStatus.READY)

    def list_scheduled(self) -> list[ContentItem]:
        return self.list_all(ContentStatus.SCHEDULED)

    def list_published(self) -> list[ContentItem]:
        return self.list_all(ContentStatus.PUBLISHED)

    def get_due_items(self) -> list[ContentItem]:
        """获取已到发布时间的定时内容。"""
        now = time.time()
        return [
            item for item in self.list_scheduled()
            if item.scheduled_at > 0 and item.scheduled_at <= now
        ]

    def approve(self, content_id: str) -> bool:
        """审批通过：draft → ready。"""
        item = self.get(content_id)
        if not item or item.status != ContentStatus.DRAFT:
            return False
        item.status = ContentStatus.READY
        self.save(item)
        return True

    def schedule(self, content_id: str, publish_time: float) -> bool:
        """设置定时发布。"""
        item = self.get(content_id)
        if not item or item.status not in (ContentStatus.DRAFT, ContentStatus.READY):
            return False
        item.status = ContentStatus.SCHEDULED
        item.scheduled_at = publish_time
        self.save(item)
        log.info("已设置定时发布: %s → %s", content_id, time.strftime("%Y-%m-%d %H:%M", time.localtime(publish_time)))
        return True

    def mark_published(self, content_id: str, platform: str, url: str = "") -> bool:
        """标记为已发布。"""
        item = self.get(content_id)
        if not item:
            return False
        item.status = ContentStatus.PUBLISHED
        item.published_at = time.time()
        if url:
            item.publish_urls[platform] = url
        self.save(item)
        return True

    def mark_failed(self, content_id: str, platform: str, error: str) -> bool:
        """标记发布失败。"""
        item = self.get(content_id)
        if not item:
            return False
        item.status = ContentStatus.FAILED
        item.publish_errors[platform] = error
        self.save(item)
        return True

    def delete(self, content_id: str) -> bool:
        path = CONTENT_DIR / f"{content_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def stats(self) -> dict[str, int]:
        """统计各状态的内容数量。"""
        counts: dict[str, int] = {}
        for f in CONTENT_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                s = data.get("status", "unknown")
                counts[s] = counts.get(s, 0) + 1
            except Exception:
                pass
        return counts


# 全局单例
store = ContentStore()
