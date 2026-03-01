# -*- coding: utf-8 -*-
"""非交互式检查社交媒体平台登录状态。"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def check_all():
    user_data = Path.home() / ".conductor-chrome"
    user_data.mkdir(exist_ok=True)

    platforms = {
        "小红书": "https://creator.xiaohongshu.com/publish/publish",
        "微博": "https://weibo.com",
    }

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )

        for name, url in platforms.items():
            print(f"\n{'='*50}")
            print(f"检查 {name}: {url}")
            page = await context.new_page()
            try:
                await page.goto(url, timeout=20000)
                await page.wait_for_load_state("networkidle", timeout=15000)
                await asyncio.sleep(3)

                current_url = page.url
                title = await page.title()

                is_login = any(kw in current_url.lower() for kw in ["login", "passport", "sign"])
                status = "未登录" if is_login else "已登录"
                icon = "❌" if is_login else "✅"

                print(f"  {icon} {name} {status}")
                print(f"  页面标题: {title}")
                print(f"  当前URL: {current_url}")

                ss_path = Path(__file__).parent / f"login_{name}.png"
                await page.screenshot(path=str(ss_path))
                print(f"  截图: {ss_path}")
            except Exception as e:
                print(f"  ⚠️  检查出错: {e}")
            finally:
                await page.close()

        print(f"\n{'='*50}")
        print("所有检查完成，5秒后关闭浏览器 ...")
        await asyncio.sleep(5)
        await context.close()


if __name__ == "__main__":
    asyncio.run(check_all())
