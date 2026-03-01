# -*- coding: utf-8 -*-
"""
登录助手 — 启动持久化浏览器，手动登录后 cookie 自动保存。

用法:
  python3 conductor/login_helper.py          # 打开登录页，等待120秒后截图并关闭
  python3 conductor/login_helper.py --wait 300  # 等待300秒
  python3 conductor/login_helper.py --check  # 仅截图检查登录状态(5秒后关闭)
"""
import argparse
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright


PLATFORMS = [
    ("小红书", "https://creator.xiaohongshu.com/login"),
    ("微博", "https://weibo.com"),
]


async def run(wait_seconds: int, check_only: bool):
    user_data = Path.home() / ".conductor-chrome"
    user_data.mkdir(exist_ok=True)

    print("=" * 60)
    print("  Conductor 登录助手")
    print(f"  浏览器数据目录: {user_data}")
    print("=" * 60)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 900},
            locale="zh-CN",
        )

        pages = []
        for name, url in PLATFORMS:
            page = await context.new_page()
            print(f"  正在打开 {name} ...")
            try:
                await page.goto(url, timeout=20000)
            except Exception:
                pass
            pages.append((name, page))
            print(f"  ✅ {name} 已打开")

        if check_only:
            print("\n  [检查模式] 3秒后截图检查状态 ...")
            await asyncio.sleep(3)
        else:
            print(f"\n  请在浏览器窗口中登录各平台。")
            print(f"  将等待 {wait_seconds} 秒后自动截图并关闭。")
            touch_file = Path(__file__).parent / ".login_done"
            touch_file.unlink(missing_ok=True)
            print(f"  提前完成登录可创建 {touch_file} 文件来跳过等待。")

            for i in range(wait_seconds):
                if touch_file.exists():
                    print("  检测到完成信号，提前结束等待。")
                    touch_file.unlink(missing_ok=True)
                    break
                await asyncio.sleep(1)

        print("\n  正在截图检查登录状态 ...")
        results = []
        for name, page in pages:
            try:
                await page.reload(timeout=15000)
                await asyncio.sleep(3)
                title = await page.title()
                url = page.url
                ss = Path(__file__).parent / f"login_{name}.png"
                await page.screenshot(path=str(ss))

                is_login_page = any(kw in url.lower() for kw in ["login", "passport", "sign"])
                logged_in = not is_login_page
                icon = "✅" if logged_in else "❌"
                status = "已登录" if logged_in else "未登录"

                print(f"  {icon} {name} {status}")
                print(f"     标题: {title}")
                print(f"     URL:  {url}")
                print(f"     截图: {ss}")
                results.append((name, logged_in))
            except Exception as e:
                print(f"  ⚠️  {name}: {e}")
                results.append((name, False))

        print("\n  正在关闭浏览器 (cookie 已自动保存) ...")
        await context.close()

        print("\n" + "=" * 60)
        all_ok = all(ok for _, ok in results)
        if all_ok:
            print("  🎉 所有平台均已登录! 自动发布功能已就绪。")
        else:
            failed = [n for n, ok in results if not ok]
            print(f"  ⚠️  以下平台未登录: {', '.join(failed)}")
            print("  请重新运行本脚本并在浏览器中完成登录。")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Conductor 登录助手")
    parser.add_argument("--wait", type=int, default=120, help="等待登录的秒数 (默认120)")
    parser.add_argument("--check", action="store_true", help="仅检查登录状态")
    args = parser.parse_args()
    asyncio.run(run(args.wait, args.check))


if __name__ == "__main__":
    main()
