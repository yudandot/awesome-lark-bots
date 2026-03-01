# -*- coding: utf-8 -*-
"""
Playwright 浏览器自动化测试脚本。
使用系统已安装的 Chrome，无需额外下载 Chromium。

用法:
  python -m conductor.test_browser           # 基础测试
  python -m conductor.test_browser --login   # 检测社交媒体登录状态
  python -m conductor.test_browser --xhs     # 打开小红书创作者后台
  python -m conductor.test_browser --weibo   # 打开微博发布页
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


async def basic_test():
    """基础测试: 启动浏览器、打开页面、截图。"""
    from playwright.async_api import async_playwright

    print("🚀 启动 Playwright + 系统 Chrome ...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel="chrome",
            headless=False,
        )
        page = await browser.new_page()

        print("📄 正在打开百度 ...")
        await page.goto("https://www.baidu.com")
        await page.wait_for_load_state("networkidle")

        title = await page.title()
        print(f"✅ 页面标题: {title}")

        screenshot_path = Path(__file__).parent / "test_screenshot.png"
        await page.screenshot(path=str(screenshot_path))
        print(f"📸 截图已保存: {screenshot_path}")

        await asyncio.sleep(3)
        await browser.close()
        print("🏁 基础测试完成!")


async def check_login(platform: str):
    """用 persistent context 检查社交媒体登录状态。"""
    from playwright.async_api import async_playwright

    user_data = Path.home() / ".conductor-chrome"
    user_data.mkdir(exist_ok=True)

    urls = {
        "xhs": ("小红书", "https://creator.xiaohongshu.com/publish/publish"),
        "weibo": ("微博", "https://weibo.com"),
    }

    name, url = urls[platform]
    print(f"🔍 正在检查 {name} 登录状态 ...")
    print(f"   用户数据目录: {user_data}")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )
        page = await context.new_page()

        print(f"📄 正在打开 {name}: {url}")
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(3)

        current_url = page.url
        is_login = "login" in current_url.lower() or "passport" in current_url.lower()

        if is_login:
            print(f"⚠️  {name} 未登录，当前页面: {current_url}")
            print(f"   请在弹出的浏览器窗口中登录 {name}")
            print("   登录完成后按回车继续 ...")
            await asyncio.get_event_loop().run_in_executor(None, input)

            current_url = page.url
            is_login = "login" in current_url.lower() or "passport" in current_url.lower()

            if not is_login:
                print(f"✅ {name} 登录成功!")
            else:
                print(f"❌ {name} 仍未登录")
        else:
            print(f"✅ {name} 已登录! 当前页面: {current_url}")

        screenshot_path = Path(__file__).parent / f"test_{platform}.png"
        await page.screenshot(path=str(screenshot_path))
        print(f"📸 截图已保存: {screenshot_path}")

        await asyncio.sleep(2)
        await context.close()

    print(f"🏁 {name} 检查完成!")


async def open_platform(platform: str):
    """打开社交媒体平台创作页面，保持浏览器打开供手动操作。"""
    from playwright.async_api import async_playwright

    user_data = Path.home() / ".conductor-chrome"
    user_data.mkdir(exist_ok=True)

    urls = {
        "xhs": ("小红书创作者中心", "https://creator.xiaohongshu.com/publish/publish"),
        "weibo": ("微博发布", "https://weibo.com"),
    }

    name, url = urls[platform]

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )
        page = await context.new_page()

        print(f"📄 正在打开 {name}: {url}")
        await page.goto(url, timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=15000)

        title = await page.title()
        print(f"✅ 已打开: {title}")
        print("   浏览器保持打开中，按回车关闭 ...")
        await asyncio.get_event_loop().run_in_executor(None, input)

        await context.close()


def main():
    parser = argparse.ArgumentParser(description="Playwright 浏览器自动化测试")
    parser.add_argument("--login", action="store_true", help="检查所有平台登录状态")
    parser.add_argument("--xhs", action="store_true", help="打开小红书创作者后台")
    parser.add_argument("--weibo", action="store_true", help="打开微博发布页")
    args = parser.parse_args()

    if args.login:
        for platform in ["xhs", "weibo"]:
            asyncio.run(check_login(platform))
    elif args.xhs:
        asyncio.run(open_platform("xhs"))
    elif args.weibo:
        asyncio.run(open_platform("weibo"))
    else:
        asyncio.run(basic_test())


if __name__ == "__main__":
    main()
