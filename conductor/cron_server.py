# -*- coding: utf-8 -*-
"""
定时触发 HTTP 服务 — 供「电脑休眠时」由外部 cron 调用，执行定时发布/定时选题。

用法：
  在 24/7 运行的服务器（VPS、云主机等）上启动：
    python3 -m conductor.cron_server --port 8765

  外部 cron（如 cron-job.org、GitHub Actions）每 15–30 分钟请求一次：
    GET https://你的服务器:8765/cron?token=CONDUCTOR_CRON_TOKEN
  可选：?scan=1 同时执行当日定时选题+生成（否则只执行「检查定时发布队列」）。

  本机休眠时，由云端定时请求该 URL，即可在服务器上执行发布，不依赖本机唤醒。
"""
from __future__ import annotations

import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_token() -> str:
    return (os.getenv("CONDUCTOR_CRON_TOKEN") or "").strip()


class CronHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/health":
            self._send(200, {"ok": True, "service": "conductor-cron"})
            return

        if path == "/cron":
            token = qs.get("token", [""])[0] or qs.get("t", [""])[0]
            expected = _get_token()
            if not expected:
                self._send(500, {"error": "CONDUCTOR_CRON_TOKEN 未配置"})
                return
            if not hmac.compare_digest(token, expected):
                self._send(403, {"error": "token 无效"})
                return

            do_scan = qs.get("scan", [""])[0].lower() in ("1", "true", "yes")
            out = {"triggered": True, "scan": do_scan}

            try:
                from conductor.scheduler import run_check_scheduled_posts, run_scheduled_scan_and_create
                published = run_check_scheduled_posts()
                out["published_count"] = published
                if do_scan:
                    ok = run_scheduled_scan_and_create()
                    out["scan_done"] = ok
            except Exception as e:
                out["error"] = str(e)
                self._send(200, out)  # 仍返回 200，便于 cron 不重试；错误在 body
                return

            self._send(200, out)
            return

        self._send(404, {"error": "not found"})

    def _send(self, code: int, body: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        print(f"[cron_server] {args[0]}", file=sys.stderr, flush=True)


def main():
    import argparse
    p = argparse.ArgumentParser(description="Conductor 定时触发 HTTP 服务（供外部 cron 调用）")
    p.add_argument("--port", type=int, default=8765, help="监听端口")
    p.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    args = p.parse_args()

    if not _get_token():
        print("请设置环境变量 CONDUCTOR_CRON_TOKEN 后再启动。", file=sys.stderr)
        sys.exit(1)

    server = HTTPServer((args.host, args.port), CronHandler)
    print(f"Conductor 定时触发服务: http://{args.host}:{args.port}  (GET /cron?token=xxx  GET /health)", file=sys.stderr, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
