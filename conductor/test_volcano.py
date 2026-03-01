#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单独测火山：文生图（Seedream）/ 文生视频（Seedance 1.5）。会加载 .env。"""
import argparse
import sys
from pathlib import Path

# 加载项目根目录 .env
_root = Path(__file__).resolve().parent.parent
_env = _root / ".env"
if _env.exists():
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                import os
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k.strip(), v)

from conductor.visual import generate_image, generate_video, download_asset, ASSETS_DIR


def _show_result(kind: str, urls, download: bool = False):
    """打印查看方式，可选下载到本地。"""
    if not urls:
        return
    if isinstance(urls, str):
        urls = [urls]
    print()
    print("=" * 60)
    print(f"  {kind} 生成成功，可从下面方式查看：")
    print("=" * 60)
    for i, u in enumerate(urls[:5], 1):
        print(f"  [{i}] 在浏览器中打开:")
        print(f"      {u}")
    print()
    if download:
        local_paths = []
        for i, u in enumerate(urls[:4]):
            try:
                ext = ".mp4" if ".mp4" in u.lower() or "video" in u.lower() else ".png"
                name = f"test_{'img' if '图' in kind else 'vid'}_{i}{ext}"
                p = download_asset(u, name)
                local_paths.append(str(p))
                print(f"  已下载到: {p}")
            except Exception as e:
                print(f"  下载失败: {e}")
        if local_paths:
            print(f"  本地目录: {ASSETS_DIR}")
        print()
    else:
        print("  提示: 复制上面链接到浏览器即可查看；加 --download 可下载到本地。")
    print("=" * 60)


def test_image(download: bool = False):
    prompt = "A cute cat on a windowsill, soft sunlight, cozy style"
    print("调用火山文生图 (Seedream)...", flush=True)
    urls = generate_image(prompt=prompt, size="1920x1920")
    _show_result("图片", urls, download=download)
    return urls


def test_video(download: bool = False):
    prompt = "A cute cat slowly turns its head on a windowsill, soft sunlight, cozy, 5 seconds"
    print("调用火山文生视频 (Seedance 1.5)...", flush=True)
    print("(任务提交后轮询结果，通常 1～3 分钟)", flush=True)
    url = generate_video(prompt=prompt, duration=5, resolution="720p", ratio="16:9", max_wait=300)
    _show_result("视频", url, download=download)
    return url


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测火山文生图/文生视频")
    parser.add_argument("--image", action="store_true", help="只测文生图 (默认)")
    parser.add_argument("--video", action="store_true", help="只测文生视频 (Seedance 1.5)")
    parser.add_argument("--all", action="store_true", help="先图后视频都测")
    parser.add_argument("--download", action="store_true", help="生成后下载到 data/conductor/assets")
    args = parser.parse_args()

    if args.all:
        args.image = True
        args.video = True
    if not args.image and not args.video:
        args.image = True

    ok = True
    if args.image:
        try:
            test_image(download=args.download)
        except Exception as e:
            print("文生图失败:", e, file=sys.stderr)
            ok = False
    if args.video:
        try:
            test_video(download=args.download)
        except Exception as e:
            print("文生视频失败:", e, file=sys.stderr)
            ok = False
    sys.exit(0 if ok else 1)
