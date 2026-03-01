# -*- coding: utf-8 -*-
"""
启动入口：python3 -m research

交互模式（默认）：
  $ python3 -m research
  进入多轮对话，输入问题即可研究，支持追问。

单次查询：
  $ python3 -m research "2026年最火的AI框架"

指定 LLM provider：
  $ python3 -m research --provider kimi "量子计算最新进展"
"""

import sys
import argparse


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Research Bot — 联网研究助手",
        usage="python3 -m research [options] [query]",
    )
    parser.add_argument("query", nargs="*", help="研究问题（不填则进入交互模式）")
    parser.add_argument("--provider", "-p", default="deepseek", help="LLM provider（默认 deepseek）")
    parser.add_argument("--model", "-m", default=None, help="指定模型名（覆盖环境变量）")
    parser.add_argument("--quiet", "-q", action="store_true", help="安静模式，不打印搜索过程")
    args = parser.parse_args()

    from research.researcher import Researcher
    r = Researcher(provider=args.provider, model_override=args.model)
    verbose = not args.quiet

    if args.query:
        query = " ".join(args.query)
        print(f"\n🔬 研究中: {query}\n")
        answer = r.research(query, verbose=verbose)
        print(f"\n{answer}\n")
        return

    print("=" * 58)
    print("  🔬 Fact-Checked Research Bot")
    print("  验证事实 · 分析机制 · 识别叙事")
    print(f"  LLM: {args.provider} / {r.model}")

    import os
    has_tavily = bool(os.environ.get("TAVILY_API_KEY", "").strip())
    search_backend = "Tavily" if has_tavily else "DuckDuckGo"
    print(f"  搜索: {search_backend}")
    print("─" * 58)
    print("  输入问题开始研究，支持多轮追问")
    print("  /new  开始新话题  |  /q  退出")
    print("=" * 58)

    while True:
        try:
            query = input("\n❓ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not query:
            continue
        if query.lower() in ("/q", "q", "quit", "exit", "退出"):
            print("👋 再见！")
            break
        if query in ("/new", "/reset", "新话题"):
            r.reset()
            print("🔄 已重置，开始新话题")
            continue

        print()
        try:
            answer = r.research(query, verbose=verbose)
            print(f"\n{answer}")
        except KeyboardInterrupt:
            print("\n⏹️  已中断")
        except Exception as e:
            print(f"\n❌ 出错了: {e}")


if __name__ == "__main__":
    main()
