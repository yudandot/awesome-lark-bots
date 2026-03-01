#!/usr/bin/env bash
# 茶馆 × 潮牌跨界快闪活动脑暴
# 使用前先确保 .env 中已配置 FEISHU_WEBHOOK（或在下面 export 你自己的）

set -e
cd "$(dirname "$0")"

# export FEISHU_WEBHOOK='https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook'

TOPIC='在洛阳茶馆里办潮牌跨界快闪活动：低成本、让创作者被打动、引起更大范围用户注意'
CONTEXT='briefs/luoyang_teahouse_guangyu.md'

python3 -m brainstorm.run --topic "$TOPIC" --context "$CONTEXT"
