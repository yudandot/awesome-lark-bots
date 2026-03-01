# sentiment/ — 舆情监控机器人

从微博、抖音、小红书、B站等 15 个平台采集社交媒体数据，生成结构化分析材料。

## 文件说明

| 文件 | 做什么 |
|------|--------|
| `bot.py` | 飞书长连接入口 — 指令解析、引导对话、调度采集 |
| `runner.py` | 流程编排 — 串联采集→统计→导出→上传的完整链路 |
| `exporter.py` | 数据导出 — 生成 JSON + Markdown 文件 |
| `feishu_api.py` | 飞书 API — 舆情机器人专用的消息发送 |
| `github_client.py` | GitHub 上传 — 采集结果推送到 GitHub 仓库 |
| `__main__.py` | 启动入口 — `python3 -m sentiment` |

## 快速使用

```bash
python3 -m sentiment
```

然后在飞书上发消息：
- `周报` — 一键生成品牌舆情周报
- `采集 品牌名 @微博 @B站 7天` — 自定义采集
- `采集 iPhone @全平台 3天 200条 +分析` — 自定义采集 + AI 分析

## 需要的环境变量

必须：`FEISHU_APP_ID` + `FEISHU_APP_SECRET` + `JOA_TOKEN`

可选：`DEEPSEEK_API_KEY`（AI 分析）、`GITHUB_TOKEN`（云存储）
