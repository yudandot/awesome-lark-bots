# -*- coding: utf-8 -*-
"""
skills CLI — 查看、测试技能。

用法：
  python -m skills list           — 列出所有已注册技能
  python -m skills test <name>    — 测试某个技能的 get_context()
  python -m skills activate <text>— 看哪些技能会被激活
"""

from __future__ import annotations

import sys


def cmd_list():
    from skills import list_skills
    skills = list_skills()
    if not skills:
        print("（暂无已注册的技能）")
        return
    print(f"已注册 {len(skills)} 个技能：\n")
    for s in skills:
        kw = ", ".join(s.trigger_keywords[:5]) if s.trigger_keywords else "—"
        bots = ", ".join(s.bot_types) if s.bot_types else "所有"
        print(f"  {s.name:15s} {s.description}")
        print(f"  {'':15s} 关键词: {kw} | 适用 bot: {bots}")
        print()


def cmd_test(name: str, **kwargs):
    from skills import get_skill
    skill = get_skill(name)
    if not skill:
        print(f"技能 '{name}' 不存在。运行 `python -m skills list` 查看可用技能。")
        sys.exit(1)
    ctx = skill.get_context(**kwargs)
    if ctx:
        print(f"[{skill.name}] get_context() 返回 {len(ctx)} 字符：\n")
        print(ctx[:2000])
        if len(ctx) > 2000:
            print(f"\n... (共 {len(ctx)} 字符，已截断)")
    else:
        print(f"[{skill.name}] get_context() 返回空。")


def cmd_activate(text: str):
    from skills import list_skills
    print(f"输入文本: \"{text}\"\n")
    activated = []
    for s in list_skills():
        if s.should_activate(text):
            activated.append(s)
            print(f"  ✓ {s.name} — 会激活")
        else:
            print(f"  ✗ {s.name} — 不激活")
    print(f"\n共 {len(activated)} 个技能会被激活。")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd == "list":
        cmd_list()
    elif cmd == "test":
        if len(args) < 2:
            print("用法: python -m skills test <skill_name> [key=value ...]")
            sys.exit(1)
        name = args[1]
        kwargs = {}
        for a in args[2:]:
            if "=" in a:
                k, v = a.split("=", 1)
                kwargs[k] = v
        cmd_test(name, **kwargs)
    elif cmd == "activate":
        if len(args) < 2:
            print("用法: python -m skills activate <text>")
            sys.exit(1)
        cmd_activate(" ".join(args[1:]))
    else:
        print(f"未知命令: {cmd}。运行 `python -m skills --help` 查看帮助。")
        sys.exit(1)


if __name__ == "__main__":
    main()
