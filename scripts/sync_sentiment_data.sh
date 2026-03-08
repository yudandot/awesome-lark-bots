#!/bin/bash
# 从云服务器同步 sentiment 数据到本地
# 用法: ./scripts/sync_sentiment_data.sh
# 定时同步: 加到 crontab，如每 30 分钟: */30 * * * * /path/to/sync_sentiment_data.sh

SERVER="root@43.106.49.162"
REMOTE_DIR="/root/AIlarkteams/data/sentiment/"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)/data/sentiment/"

mkdir -p "$LOCAL_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 同步 sentiment 数据..."
rsync -avz --progress \
    -e "ssh -o StrictHostKeyChecking=no" \
    "$SERVER:$REMOTE_DIR" "$LOCAL_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 同步完成 → $LOCAL_DIR"
