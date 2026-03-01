#!/usr/bin/env bash
# 在部署机器上运行：检查舆情 bot 容器状态与最近日志
# 用法：bash scripts/check_sentiment.sh  或  docker compose 在项目根目录时：bash scripts/check_sentiment.sh

set -e
cd "$(dirname "$0")/.."

echo "========== 1. 容器状态 =========="
docker compose ps sentiment 2>/dev/null || docker-compose ps sentiment 2>/dev/null || true
echo ""
echo "========== 2. 最近 80 行日志（错误/301 会标出）=========="
CONTAINER=$(docker compose ps -q sentiment 2>/dev/null || docker-compose ps -q sentiment 2>/dev/null || true)
if [ -z "$CONTAINER" ]; then
  echo "未找到 sentiment 容器，尝试按名称查找..."
  CONTAINER=$(docker ps -q -f name=sentiment 2>/dev/null | head -1)
fi
if [ -n "$CONTAINER" ]; then
  docker logs --tail 80 "$CONTAINER" 2>&1 | while read -r line; do
    if echo "$line" | grep -qE "301|Error|ERROR|Exception|Traceback|失败"; then
      echo ">>> $line"
    else
      echo "$line"
    fi
  done
else
  echo "未找到运行中的 sentiment 容器。"
fi
echo ""
echo "========== 3. 简要说明 =========="
echo "- 若容器为 Up 且无报错：舆情 bot 在运行，飞书发消息应能触发。"
echo "- 若出现 301：多为 JOA 采集接口重定向，请检查 JOA_BASE_URL 或 JustOneAPI 服务。"
echo "- 若出现 SENTIMENT_FEISHU_APP_ID 未设置：请在 .env 中配置舆情机器人飞书凭证。"
