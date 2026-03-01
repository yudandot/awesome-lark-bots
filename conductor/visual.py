# -*- coding: utf-8 -*-
"""
视觉素材生成 — 通过火山方舟 Ark SDK 调用 Seedance / Seedream 生成图片和视频。

支持能力：
  - 文生图：Seedream（prompt → 图片 URL）
  - 文生视频：Seedance（prompt → 视频 URL）
  - 图生视频：Seedance（图片 + prompt → 视频 URL）

认证方式：
  火山方舟统一 API Key（和豆包 LLM 是同一个平台）。
  需要在 .env 中配置 ARK_API_KEY（或复用 DOUBAO_API_KEY）。
  获取方式：https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey

前置条件：
  pip install 'volcengine-python-sdk[ark]'
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import requests

from conductor.config import DATA_DIR, log

ASSETS_DIR = DATA_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# 默认模型（需在火山方舟控制台开通对应能力；也可用接入点 ID 如 ep-xxx）
DEFAULT_IMAGE_MODEL = "doubao-seedream-4-5-251128"
DEFAULT_VIDEO_MODEL = "doubao-seedance-1-5-pro-251215"

# Base URL（国内默认）
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


def _get_client():
    """获取 Ark 客户端，优先使用 ARK_API_KEY，否则回退到 DOUBAO_API_KEY。"""
    from volcenginesdkarkruntime import Ark

    api_key = (
        os.getenv("ARK_API_KEY", "").strip()
        or os.getenv("DOUBAO_API_KEY", "").strip()
    )
    if not api_key:
        raise ValueError(
            "未配置火山方舟 API Key。请在 .env 中设置：\n"
            "  ARK_API_KEY=your_api_key\n"
            "  或\n"
            "  DOUBAO_API_KEY=your_api_key\n"
            "获取地址：https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey"
        )

    base_url = os.getenv("DOUBAO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    return Ark(api_key=api_key, base_url=base_url)


# ── 文生图（Seedream） ────────────────────────────────────────

def generate_image(
    prompt: str,
    size: str = "1920x1920",
    model: str = "",
    seed: int = -1,
    response_format: str = "url",
) -> list[str]:
    """
    文生图：根据 prompt 生成图片。

    Args:
        prompt: 图片描述（中文或英文）
        size: 尺寸（Seedream 4.5 至少 1920x1920），如 "1920x1920", "2048x1792"
        model: 模型名（默认 seedream-3-0）
        seed: 随机种子（-1 = 随机）
        response_format: "url" 或 "b64_json"

    Returns:
        图片 URL 或本地路径的列表
    """
    model = model or os.getenv("ARK_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)
    log.info("Ark 文生图: model=%s prompt=%s... size=%s", model, prompt[:50], size)

    client = _get_client()

    kwargs = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "response_format": response_format,
    }
    if seed >= 0:
        kwargs["seed"] = seed

    try:
        resp = client.images.generate(**kwargs, timeout=120)
    except Exception as e:
        log.error("Ark 文生图调用失败: %s", e)
        raise

    if resp.error and resp.error.code:
        raise RuntimeError(f"Ark 文生图失败: [{resp.error.code}] {resp.error.message}")

    urls = []
    for img in resp.data:
        if img.url:
            urls.append(img.url)
        elif img.b64_json:
            path = _save_base64_image(img.b64_json, f"img_{uuid.uuid4().hex[:8]}")
            urls.append(str(path))

    log.info("Ark 文生图完成: %d 张", len(urls))
    return urls


# ── 文生视频 / 图生视频（Seedance）────────────────────────────

def generate_video(
    prompt: str,
    image_url: str = "",
    duration: int = 5,
    resolution: str = "720p",
    ratio: str = "16:9",
    model: str = "",
    camera_fixed: bool = False,
    seed: int = -1,
    max_wait: int = 300,
) -> str:
    """
    视频生成：文生视频或图生视频。

    Args:
        prompt: 视频描述
        image_url: 参考图片 URL（有则为图生视频，无则为文生视频）
        duration: 时长秒数（5 或 10）
        resolution: 分辨率 "480p" / "720p" / "1080p"
        ratio: 宽高比 "16:9" / "4:3" / "1:1" / "9:16" / "21:9"
        model: 模型名（默认 Seedance 1.5：doubao-seedance-1-5-pro-251215）
        camera_fixed: 是否固定镜头
        seed: 随机种子（-1 = 随机）
        max_wait: 最长等待时间（秒）

    Returns:
        视频 URL
    """
    model = model or os.getenv("ARK_VIDEO_MODEL", DEFAULT_VIDEO_MODEL)
    log.info(
        "Ark 视频生成: model=%s prompt=%s... duration=%ds resolution=%s ratio=%s",
        model, prompt[:50], duration, resolution, ratio,
    )

    client = _get_client()

    content = []
    if image_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url},
        })
    content.append({"type": "text", "text": prompt})

    kwargs = {
        "model": model,
        "content": content,
        "resolution": resolution,
        "ratio": ratio,
        "duration": duration,
    }
    if camera_fixed:
        kwargs["camera_fixed"] = True
    if seed >= 0:
        kwargs["seed"] = seed

    try:
        task = client.content_generation.tasks.create(**kwargs, timeout=30)
    except Exception as e:
        log.error("Ark 视频任务创建失败: %s", e)
        raise

    task_id = task.id
    log.info("Ark 视频任务已创建: task_id=%s", task_id)

    return _poll_video_task(client, task_id, max_wait)


def _poll_video_task(client, task_id: str, max_wait: int = 300) -> str:
    """轮询视频生成任务直到完成。"""
    start = time.time()
    while time.time() - start < max_wait:
        time.sleep(5)
        try:
            result = client.content_generation.tasks.get(task_id=task_id)
        except Exception as e:
            log.warning("轮询任务出错 (将重试): %s", e)
            continue

        status = result.status
        elapsed = time.time() - start

        if status == "succeeded":
            video_url = result.content.video_url
            log.info("视频生成完成 (%.0fs): %s", elapsed, video_url[:80] if video_url else "无URL")
            return video_url

        if status in ("failed", "cancelled"):
            err_msg = result.error.message if result.error else "未知错误"
            raise RuntimeError(f"视频任务{status}: {err_msg}")

        log.debug("视频生成中... status=%s (%.0fs/%ds)", status, elapsed, max_wait)

    raise TimeoutError(f"视频任务超时 ({max_wait}s): {task_id}")


def list_video_tasks(status: str = None, limit: int = 10) -> list:
    """查询视频生成任务列表。"""
    client = _get_client()
    resp = client.content_generation.tasks.list(
        page_size=limit,
        status=status,
    )
    return resp.data if hasattr(resp, "data") else []


def cancel_video_task(task_id: str):
    """取消或删除视频生成任务。"""
    client = _get_client()
    client.content_generation.tasks.delete(task_id)
    log.info("已取消任务: %s", task_id)


# ── 工具函数 ──────────────────────────────────────────────────

def _save_base64_image(b64_data: str, name: str) -> Path:
    """将 base64 图片保存到本地。"""
    img_bytes = base64.b64decode(b64_data)
    path = ASSETS_DIR / f"{name}.png"
    path.write_bytes(img_bytes)
    return path


def download_asset(url: str, filename: str = "") -> Path:
    """下载图片/视频到本地 assets 目录。"""
    if not filename:
        ext = ".mp4" if any(v in url.lower() for v in ("video", ".mp4", "mp4")) else ".png"
        filename = f"asset_{uuid.uuid4().hex[:8]}{ext}"

    path = ASSETS_DIR / filename
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    path.write_bytes(resp.content)
    log.info("素材已下载: %s (%.1f KB)", path.name, len(resp.content) / 1024)
    return path
