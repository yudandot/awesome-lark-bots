# -*- coding: utf-8 -*-
"""
自媒体助手 CLI — 不需要飞书也能运行完整 Pipeline。

用法：
  python3 -m conductor.cli --topic "春天穿搭分享"
  python3 -m conductor.cli --topic "春天穿搭" --platforms "小红书 抖音"
  python3 -m conductor.cli --topic "联动活动" --deep --brand sky
  python3 -m conductor.cli --list                  # 查看内容仓库
  python3 -m conductor.cli --detail <content_id>   # 查看内容详情
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from conductor.config import Platform, Stage
from conductor.pipeline import run_pipeline, PipelineRun
from conductor.store import store, ContentItem


def _print_run_result(run: PipelineRun):
    """打印 Pipeline 执行结果。"""
    print()
    print("=" * 60)
    print(f"Pipeline 完成 | 状态: {run.status} | 耗时: {run.elapsed_sec():.1f}s")
    print("=" * 60)

    if run.error:
        print(f"\n错误: {run.error}")

    if run.trends:
        print(f"\n📡 扫描到 {len(run.trends)} 条热点趋势")

    if run.ideas:
        print(f"\n💡 产出 {len(run.ideas)} 个创意：")
        for i, idea in enumerate(run.ideas):
            marker = " ★" if idea == run.selected_idea else ""
            print(f"  [{i}] {idea.title} (吸引力:{idea.estimated_appeal:.0%}){marker}")
            print(f"      角度: {idea.angle}")
            print(f"      钩子: {idea.hook}")

    if run.draft:
        print(f"\n📝 内容已生成 | 质量分: {run.draft.quality_score:.0%}")
        if run.draft.quality_feedback:
            print(f"   评价: {run.draft.quality_feedback}")

        if run.draft.platform_copy:
            print("\n   ─── 各平台文案 ───")
            for plat, copy in run.draft.platform_copy.items():
                print(f"\n   [{plat}]")
                for line in copy.split("\n")[:10]:
                    print(f"   {line}")
                if copy.count("\n") > 10:
                    print(f"   ... (共 {copy.count(chr(10))+1} 行)")

        if run.draft.visual_prompt:
            print("\n   ─── 视觉 Prompt ───")
            print(f"   {run.draft.visual_prompt[:500]}")
            if len(run.draft.visual_prompt) > 500:
                print(f"   ... (共 {len(run.draft.visual_prompt)} 字)")

        if run.draft.visual_prompt_en:
            print("\n   ─── Seedance 英文版 ───")
            print(f"   {run.draft.visual_prompt_en[:300]}")

    if run.publish_results:
        print(f"\n📦 内容已存入仓库")
        for r in run.publish_results:
            status = "✅" if r.success else "❌"
            print(f"  {status} {r.platform.value if hasattr(r.platform, 'value') else r.platform}: {r.post_id or r.error}")

    print(f"\nrun_id: {run.run_id}")
    print(f"记录已保存到: data/conductor/run_{run.run_id}.json")
    print()


def _print_content_list(status_filter: str = ""):
    status = status_filter.strip().lower() or None
    if status and status not in ("draft", "ready", "scheduled", "published", "failed"):
        print("--status 可选: draft | ready | scheduled | published | failed")
        return
    items = store.list_all(status=status)
    if not items:
        print("内容仓库为空。" if not status else f"没有状态为 [{status}] 的内容。")
        return

    title = f"内容仓库 ({len(items)} 条)" + (f" [仅 {status}]" if status else "")
    print(f"\n{title}：")
    print("-" * 70)
    for item in items:
        status_emoji = {"draft": "📝", "ready": "✅", "scheduled": "⏰", "published": "🎉", "failed": "❌"}.get(item.status, "❓")
        ts = time.strftime("%m/%d %H:%M", time.localtime(item.created_at))
        print(f"  {status_emoji} {item.content_id}  {item.title[:40]:40s}  [{item.status:10s}]  {ts}")
    print()


def _do_import_dir(
    import_dir: str,
    title: str = "",
    body: str = "",
    brief: str = "",
    do_publish: bool = False,
):
    """自带素材入库：目录内放图片 + content.json 或 content.md（或 --title/--body / --brief），写入内容仓库后可选发布。"""
    from pathlib import Path
    from conductor.store import ContentItem, ContentStatus

    root = Path(import_dir).resolve()
    if not root.is_dir():
        print(f"目录不存在: {root}")
        return

    # 收集图片（支持本地路径，发布时直接用）
    ext = {".png", ".jpg", ".jpeg", ".webp"}
    asset_paths = []
    for f in sorted(root.iterdir()):
        if f.is_file() and f.suffix.lower() in ext and f.name not in ("content.json", "content.md"):
            asset_paths.append(str(f.resolve()))
    if not asset_paths:
        print(f"目录内未找到图片（支持 .png/.jpg/.jpeg/.webp）: {root}")
        return

    # 标题 + 正文：优先 content.json，其次 content.md，再次 --title/--body，最后 --brief 用 LLM 生成
    hashtags = []
    json_path = root / "content.json"
    md_path = root / "content.md"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            title = title or data.get("title", "")
            body = body or data.get("body", "")
            hashtags = data.get("hashtags") or []
        except Exception as e:
            print(f"读取 content.json 失败: {e}")
    if (not title and not body) and md_path.exists():
        raw = md_path.read_text(encoding="utf-8").strip()
        lines = raw.split("\n", 1)
        title = title or (lines[0].strip() if lines else "")
        body = body or (lines[1].strip() if len(lines) > 1 else "")
    if not title and not body and brief:
        try:
            from core.llm import chat_completion
            prompt = f"请为以下「一句话描述」生成一条小红书图文笔记的标题和正文。\n描述：{brief}\n\n要求：标题一句话（可带 emoji），正文 2～4 行口语化、有吸引力。只输出两行，第一行是标题，第二行是正文，中间不要换行符以外的分隔。"
            raw = chat_completion(provider="deepseek", system="你是小红书文案专家。只输出标题和正文，不要解释。", user=prompt, temperature=0.7)
            parts = raw.strip().split("\n", 1)
            title = parts[0].strip() if parts else ""
            body = parts[1].strip() if len(parts) > 1 else ""
            if title or body:
                print("已用 LLM 根据 brief 生成标题与正文")
        except Exception as e:
            print(f"LLM 生成文案失败: {e}")
    if not title:
        title = Path(asset_paths[0]).stem[:30]

    full_copy = f"{title}\n\n{body}".strip()
    if hashtags:
        full_copy += "\n\n" + " ".join(f"#{t.lstrip('#')}" for t in hashtags[:10])

    item = ContentItem(
        title=title[:80],
        topic=title,
        content_type="image_post",
        platform_copy={"xiaohongshu": full_copy},
        hashtags=hashtags if isinstance(hashtags, list) else [],
        generated_assets=asset_paths,
        target_platforms=["xiaohongshu"],
        status=ContentStatus.DRAFT,
    )
    content_id = store.save(item)
    print(f"已入库: {content_id}  {title[:50]}")
    print(f"  素材: {len(asset_paths)} 张")

    if do_publish:
        from conductor.stages.publisher import publish_content
        print("正在发布到小红书...")
        result = publish_content(content_id, "xiaohongshu")
        if result.success:
            store.mark_published(content_id, "xiaohongshu", result.post_url or "")
            print(f"✅ 发布成功: {result.post_url or content_id}")
        else:
            print(f"❌ 发布失败: {result.error}")
    else:
        print("未加 --publish，仅入库。发布请执行: python3 -m conductor.cli --republish", content_id)


def _print_content_detail(content_id: str):
    item = store.get(content_id)
    if not item:
        print(f"未找到内容: {content_id}")
        return

    print(f"\n{'=' * 60}")
    print(f"内容详情: {item.content_id}")
    print(f"{'=' * 60}")
    print(f"标题: {item.title}")
    print(f"状态: {item.status}")
    print(f"质量分: {item.quality_score:.0%}")
    print(f"创建时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item.created_at))}")

    if item.platform_copy:
        for plat, copy in item.platform_copy.items():
            print(f"\n--- {plat} 文案 ---")
            print(copy)

    if item.visual_prompt:
        print(f"\n--- 视觉 Prompt ---")
        print(item.visual_prompt)

    if item.visual_prompt_en:
        print(f"\n--- Seedance 英文版 ---")
        print(item.visual_prompt_en)
    print()


def main():
    parser = argparse.ArgumentParser(description="自媒体助手 CLI")
    parser.add_argument("--topic", default="", help="内容主题")
    parser.add_argument("--brand", default="", help="品牌（留空则不指定）")
    parser.add_argument("--platforms", default="小红书", help="目标平台（空格分隔）")
    parser.add_argument("--content-type", default="short_video", choices=["short_video", "image_post", "article"])
    parser.add_argument("--deep", action="store_true", help="深度模式（脑暴→creative prompt→创作）")
    parser.add_argument("--publish", action="store_true", help="生成后直接发布（不存草稿）；不传则用 CONDUCTOR_AUTO_PUBLISH 环境变量")
    parser.add_argument("--list", action="store_true", help="列出内容仓库")
    parser.add_argument("--status", default="", help="与 --list 同用，只显示某状态: draft | ready | scheduled | published | failed")
    parser.add_argument("--detail", default="", help="查看内容详情")
    parser.add_argument("--approve", default="", help="审批通过指定内容")
    parser.add_argument("--republish", default="", metavar="ID", help="重新发布指定内容到小红书，例: --republish b2791d374757")
    parser.add_argument("--generate-and-publish", default="", metavar="ID", help="为草稿补跑火山生成素材并发布到小红书，例: --generate-and-publish a73ac0fc55f2")
    parser.add_argument("--import-dir", default="", metavar="DIR", help="自带素材入库：目录内放图片 + content.json 或 content.md 写标题/正文，见 conductor/IMPORT_ASSETS.md")
    parser.add_argument("--title", default="", help="与 --import-dir 同用：直接指定发布标题（否则从 content.json/md 读）")
    parser.add_argument("--body", default="", help="与 --import-dir 同用：直接指定正文（否则从 content.json/md 读）")
    parser.add_argument("--brief", default="", help="与 --import-dir 同用：一句话描述，由 LLM 生成标题+正文（无 content.json 且未填 --title/--body 时用）")
    args = parser.parse_args()

    if args.import_dir:
        _do_import_dir(
            args.import_dir.strip(),
            title=args.title.strip(),
            body=args.body.strip(),
            brief=args.brief.strip(),
            do_publish=args.publish,
        )
        return

    if args.generate_and_publish:
        content_id = args.generate_and_publish.strip()
        item = store.get(content_id)
        if not item:
            print(f"未找到内容: {content_id}")
            return
        if not (item.visual_prompt or item.visual_prompt_en):
            print(f"内容 {content_id} 无视觉文案，无法生成素材")
            return
        # 若无素材则调用火山生成
        if not (item.generated_assets or len(item.generated_assets) > 0):
            from conductor.stages.content_factory import best_image_prompt_from_text
            from conductor.visual import generate_image
            prompt = best_image_prompt_from_text(item.visual_prompt or "", item.visual_prompt_en or "")
            if not prompt:
                print("无法从视觉文案中提取可用 prompt，跳过生成")
            else:
                print(f"正在调用火山生成图片 (prompt 长度: {len(prompt)})...")
                try:
                    urls = generate_image(prompt=prompt[:1500], size="1920x1920")
                    if urls:
                        item.generated_assets = urls
                        store.save(item)
                        print(f"已生成 {len(urls)} 张图并更新内容")
                    else:
                        print("火山未返回图片")
                except Exception as e:
                    print(f"火山生成失败: {e}")
                    return
        else:
            print(f"已有 {len(item.generated_assets)} 个素材，直接发布")
        from conductor.stages.publisher import publish_content
        print(f"发布: {content_id} → 小红书")
        result = publish_content(content_id, "xiaohongshu")
        if result.success:
            store.mark_published(content_id, "xiaohongshu", result.post_url or "")
            print(f"✅ 发布成功: {result.post_url or content_id}")
        else:
            print(f"❌ 发布失败: {result.error}")
        return

    if args.list:
        _print_content_list(args.status)
        return

    if args.detail:
        _print_content_detail(args.detail)
        return

    if args.republish:
        from conductor.stages.publisher import publish_content
        content_id = args.republish.strip()
        print(f"重新发布: {content_id} → 小红书")
        result = publish_content(content_id, "xiaohongshu")
        if result.success:
            print(f"✅ 发布成功: {result.post_url or content_id}")
        else:
            print(f"❌ 发布失败: {result.error}")
        return

    if args.approve:
        if store.approve(args.approve):
            print(f"✅ 已审批通过: {args.approve}")
        else:
            print(f"❌ 审批失败: {args.approve}")
        return

    if not args.topic:
        parser.print_help()
        return

    platforms = args.platforms.split()
    auto_publish = args.publish or (os.environ.get("CONDUCTOR_AUTO_PUBLISH", "").lower() in ("1", "true", "yes"))
    print(f"🚀 自媒体助手启动")
    print(f"   主题: {args.topic}")
    print(f"   模式: {'深度（脑暴→creative prompt→创作）' if args.deep else '快速（创意+创作）'}")
    print(f"   品牌: {args.brand}")
    print(f"   平台: {', '.join(platforms)}")
    print(f"   发布: {'直接发布' if auto_publish else '仅存草稿'}")
    print()

    def on_stage(run, stage):
        stage_names = {
            "scan": "扫描热点", "ideate": "产出创意",
            "create": "生成内容", "publish": "发布到平台",
            "engage": "互动", "review": "复盘",
        }
        print(f"  ✓ {stage_names.get(stage.value, stage.value)} 完成")

    run = run_pipeline(
        topic=args.topic,
        brand=args.brand,
        platforms=platforms,
        content_type=args.content_type,
        deep_mode=args.deep,
        auto_publish=auto_publish,
        on_stage_complete=on_stage,
    )

    _print_run_result(run)


if __name__ == "__main__":
    main()
