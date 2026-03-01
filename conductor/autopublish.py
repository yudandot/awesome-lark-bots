# -*- coding: utf-8 -*-
"""
自动发布 — 通过 Playwright 浏览器自动化发布到社交媒体。

工作原理：
  1. 以调试模式启动 Chrome，手动登录一次平台账号
  2. 之后 Playwright 连接到已登录的浏览器实例
  3. 模拟真人操作完成发布

支持平台：
  - 小红书（图文笔记）：流程与选择器参考 https://github.com/xpzouying/xiaohongshu-mcp
  - 微博（图文微博）

安全建议：
  - 发布间隔建议 > 30 分钟，避免触发风控
  - 建议先在飞书审批后再自动发布
  - 首次使用请手动登录一次

前置安装：
  pip install playwright
  # 无需 playwright install chromium，直接使用系统 Chrome
"""
from __future__ import annotations

import asyncio
import os
import random
import time
from pathlib import Path
from typing import Optional

from conductor.config import log

# 延迟 import，不强制依赖 playwright
_playwright = None


def _ensure_playwright():
    global _playwright
    if _playwright is not None:
        return
    try:
        import playwright
        _playwright = True
    except ImportError:
        raise ImportError(
            "自动发布需要 playwright。请安装：\n"
            "  pip install playwright"
        )


async def _get_browser(headless: bool = False):
    """连接到已有的 Chrome 实例，或启动新的持久化浏览器。"""
    from playwright.async_api import async_playwright

    cdp_url = os.getenv("CHROME_CDP_URL", "")
    p = await async_playwright().start()

    if cdp_url:
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            log.info("已连接到 Chrome 调试端口: %s", cdp_url)
            return p, browser
        except Exception:
            log.info("无法连接到 Chrome 调试端口，回退到启动新浏览器")

    user_data = os.getenv("CHROME_USER_DATA", str(Path.home() / ".conductor-chrome"))
    browser = await p.chromium.launch_persistent_context(
        user_data_dir=user_data,
        channel="chrome",
        headless=headless,
        viewport={"width": 1280, "height": 800},
        locale="zh-CN",
    )
    return p, browser


async def _random_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    """模拟人类操作的随机延迟。"""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


# ── 小红书发布 ────────────────────────────────────────────────
# 流程参考：https://github.com/xpzouying/xiaohongshu-mcp （创作者中心发布页结构、选择器）

XHS_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"


async def _xhs_remove_popover(page):
    """移除可能遮挡的弹窗（参考 xiaohongshu-mcp）。"""
    try:
        pop = page.locator("div.d-popover").first
        if await pop.count() > 0:
            await pop.evaluate("el => el.remove()")
            log.info("小红书: 已移除遮挡弹窗")
    except Exception:
        pass


async def _xhs_click_upload_tab(page, tab_name: str = "上传图文"):
    """点击发布页的「上传图文」等 Tab（参考 xiaohongshu-mcp：div.creator-tab）。"""
    await page.locator("div.upload-content").first.wait_for(state="visible", timeout=15000)
    await _random_delay(1, 2)
    tabs = page.locator("div.creator-tab")
    n = await tabs.count()
    for i in range(n):
        try:
            t = tabs.nth(i)
            if await t.is_visible():
                text = (await t.text_content()) or ""
                if tab_name in text.strip():
                    await t.click()
                    log.info("小红书: 已点击 Tab [%s]", tab_name)
                    await _random_delay(1, 2)
                    return
        except Exception:
            continue
    raise RuntimeError(f"未找到发布 Tab「{tab_name}」，页面可能已改版")


async def _xhs_click_upload_image_area(page):
    """点击「上传图文」后，再点击「上传图片」区域以打开上传入口。"""
    await _random_delay(1, 2)
    for text in ["上传图片", "点击上传", "添加图片", "上传"]:
        try:
            btn = page.get_by_text(text, exact=False).first
            await btn.wait_for(state="visible", timeout=3000)
            await btn.click()
            log.info("小红书: 已点击 [%s]", text)
            await _random_delay(1, 2)
            return
        except Exception:
            continue
    # 若找不到文案，尝试点击 .upload-input 所在的可点击父元素
    try:
        upload_area = page.locator(".upload-input").first
        await upload_area.wait_for(state="visible", timeout=3000)
        await upload_area.click()
        log.info("小红书: 已点击上传区域")
        await _random_delay(1, 2)
    except Exception:
        pass


async def _xhs_wait_upload_complete(page, expected_count: int, max_wait: int = 60):
    """等待图片上传完成（参考 xiaohongshu-mcp：.img-preview-area .pr 数量）。"""
    import asyncio
    start = time.time()
    while (time.time() - start) < max_wait:
        try:
            els = page.locator(".img-preview-area .pr")
            count = await els.count()
            if count >= expected_count:
                return
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError(f"第 {expected_count} 张图片上传超时({max_wait}s)")


async def _publish_xiaohongshu_async(
    title: str,
    content: str,
    image_paths: list[str | Path] = None,
    hashtags: list[str] = None,
) -> str:
    """发布小红书图文笔记（异步）。流程与选择器参考 xiaohongshu-mcp。"""
    _ensure_playwright()
    p, browser = await _get_browser()

    try:
        context = browser.contexts[0] if hasattr(browser, "contexts") else browser
        page = await context.new_page()
        page.set_default_timeout(30000)

        await page.goto(XHS_PUBLISH_URL)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await _random_delay(2, 3)

        if "login" in page.url.lower():
            await page.close()
            raise RuntimeError(
                "小红书未登录。请先运行 login_helper 或手动登录创作者中心。"
            )

        # 点击「上传图文」Tab（参考 xiaohongshu-mcp）
        await _xhs_click_upload_tab(page, "上传图文")
        await _xhs_remove_popover(page)
        await _random_delay(2, 4)  # 等表单区域渲染

        # 再点击「上传图片」以打开上传入口（用户反馈：点完上传图文后需再点上传播图）
        await _xhs_click_upload_image_area(page)

        # 上传图片：首张用 .upload-input，后续用 input[type=file]；每张后等待预览（参考 xiaohongshu-mcp）
        if image_paths:
            valid_paths = [str(Path(p).resolve()) for p in image_paths if Path(p).exists()]
            if not valid_paths:
                log.warning("小红书: 无有效本地图片路径，将发布纯文字")
            else:
                for i, img_path in enumerate(valid_paths[:9]):  # 最多 9 张
                    selector = ".upload-input" if i == 0 else 'input[type="file"]'
                    try:
                        inp = page.locator(selector).first
                        await inp.wait_for(state="attached", timeout=10000)
                        await inp.set_input_files(img_path)
                        await _xhs_wait_upload_complete(page, i + 1, max_wait=60)
                        await _random_delay(1, 2)
                    except Exception as e:
                        log.warning("小红书: 上传第 %d 张失败: %s", i + 1, e)
                        raise
                log.info("小红书: 已上传 %d 张图片", len(valid_paths))
                await _random_delay(2, 4)

        # 标题：div.d-input input（参考 xiaohongshu-mcp），多种备选
        title_input = None
        for selector in [
            "div.d-input input",
            "div.title-container input",
            'input[placeholder*="标题"]',
            'input[placeholder*="填写"]',
            'input[type="text"]',
            "input:not([type='file']):not([type='hidden'])",
        ]:
            try:
                loc = page.locator(selector).first
                await loc.wait_for(state="visible", timeout=6000)
                title_input = loc
                break
            except Exception:
                continue
        if not title_input:
            try:
                title_input = page.get_by_role("textbox").first
                await title_input.wait_for(state="visible", timeout=5000)
            except Exception:
                pass
        if not title_input:
            raise RuntimeError("未找到标题输入框，小红书发布页可能已改版")
        await title_input.fill(title[:20])
        log.info("小红书: 已填写标题")
        await _random_delay(0.5, 1)

        # 正文：div.ql-editor（Quill）或带 data-placeholder 的正文区（参考 xiaohongshu-mcp）
        full_content = content
        if hashtags:
            full_content += "\n\n" + " ".join(f"#{t.lstrip('#')}" for t in hashtags[:10])

        content_elem = None
        try:
            content_elem = page.locator("div.ql-editor").first
            await content_elem.wait_for(state="visible", timeout=5000)
        except Exception:
            try:
                content_elem = page.locator('[data-placeholder*="正文"], [data-placeholder*="描述"]').first
                await content_elem.wait_for(state="visible", timeout=5000)
            except Exception:
                ce_all = page.locator('[contenteditable="true"]')
                if await ce_all.count() >= 2:
                    content_elem = ce_all.nth(1)
                else:
                    content_elem = ce_all.first
                await content_elem.wait_for(state="visible", timeout=5000)
        if content_elem:
            await content_elem.click()
            await _random_delay(0.3, 0.6)
            await content_elem.fill(full_content[:1000])
            log.info("小红书: 已填写正文")
        await _random_delay(1, 2)

        # 发布按钮：.publish-page-publish-btn button.bg-red（参考 xiaohongshu-mcp）
        publish_btn = page.locator(".publish-page-publish-btn button.bg-red").first
        try:
            await publish_btn.wait_for(state="visible", timeout=8000)
        except Exception:
            publish_btn = page.locator('button:has-text("发布")').first
            await publish_btn.wait_for(state="visible", timeout=5000)
        await publish_btn.click()
        log.info("小红书: 已点击发布")

        await _random_delay(3, 6)

        # 若有二次确认弹窗
        for confirm_text in ["确认", "确定", "确认发布", "立即发布"]:
            try:
                btn = page.locator(f'button:has-text("{confirm_text}")').first
                await btn.wait_for(state="visible", timeout=2000)
                await btn.click()
                log.info("小红书: 已点击二次确认")
                await _random_delay(2, 4)
                break
            except Exception:
                continue

        await _random_delay(5, 10)
        current_url = page.url
        await page.close()
        return current_url

    except Exception as e:
        log.error("小红书发布失败: %s", e)
        raise
    finally:
        await p.stop()


# ── 微博发布 ──────────────────────────────────────────────────

async def _publish_weibo_async(
    content: str,
    image_paths: list[str | Path] = None,
) -> str:
    """发布微博（异步）。"""
    _ensure_playwright()
    p, browser = await _get_browser()

    try:
        context = browser.contexts[0] if hasattr(browser, 'contexts') else browser
        page = await context.new_page()

        await page.goto("https://weibo.com")
        await page.wait_for_load_state("networkidle", timeout=30000)
        await _random_delay(2, 4)

        if "login" in page.url.lower() or "passport" in page.url.lower():
            await page.close()
            raise RuntimeError(
                "微博未登录。请先手动登录：\n"
                "1. 启动 Chrome: chrome --remote-debugging-port=9222\n"
                "2. 打开 https://weibo.com 并登录\n"
                "3. 登录后重新执行发布"
            )

        # 点击发布框
        compose_box = page.locator('[class*="Form_input"]').first
        await compose_box.click()
        await _random_delay()

        # 输入内容
        textarea = page.locator('textarea[class*="Form"]').first
        await textarea.fill(content[:2000])
        log.info("微博: 已填写内容")

        # 上传图片
        if image_paths:
            file_input = page.locator('input[type="file"][accept*="image"]').first
            for img_path in image_paths:
                await file_input.set_input_files(str(img_path))
                await _random_delay(1, 3)
            log.info("微博: 已上传 %d 张图片", len(image_paths))
            await _random_delay(3, 5)

        # 点击发布
        publish_btn = page.locator('button:has-text("发布"), [class*="btn_pub"]').first
        await publish_btn.click()
        log.info("微博: 已点击发布")

        await _random_delay(3, 5)
        current_url = page.url
        await page.close()
        return current_url

    except Exception as e:
        log.error("微博发布失败: %s", e)
        raise
    finally:
        await p.stop()


# ── 同步接口（供非异步代码调用）────────────────────────────────

def publish_xiaohongshu(
    title: str,
    content: str,
    image_paths: list[str | Path] = None,
    hashtags: list[str] = None,
) -> str:
    """同步版本：发布小红书笔记。返回发布 URL。"""
    return asyncio.run(_publish_xiaohongshu_async(title, content, image_paths, hashtags))


def publish_weibo(
    content: str,
    image_paths: list[str | Path] = None,
) -> str:
    """同步版本：发布微博。返回发布 URL。"""
    return asyncio.run(_publish_weibo_async(content, image_paths))


def check_login_status(platform: str) -> tuple[bool, str]:
    """
    检查平台登录状态。

    Returns:
        (is_logged_in, message)
    """
    async def _check():
        _ensure_playwright()
        p, browser = await _get_browser(headless=True)
        try:
            context = browser.contexts[0] if hasattr(browser, 'contexts') else browser
            page = await context.new_page()

            urls = {
                "xiaohongshu": "https://creator.xiaohongshu.com/publish/publish",
                "weibo": "https://weibo.com/u/page/publish/all",
            }
            url = urls.get(platform)
            if not url:
                return False, f"不支持的平台: {platform}"

            await page.goto(url, timeout=15000)
            await asyncio.sleep(3)

            is_login_page = "login" in page.url.lower() or "passport" in page.url.lower()
            await page.close()

            if is_login_page:
                return False, f"{platform} 未登录"
            return True, f"{platform} 已登录"

        finally:
            await p.stop()

    try:
        return asyncio.run(_check())
    except ImportError as e:
        return False, str(e)
    except Exception as e:
        return False, f"检查失败: {e}"
