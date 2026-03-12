# 自媒体助手 (`conductor/`)

端到端内容生产流水线：输入一个主题，自动完成 **选题→脑暴→规划→创作→质量修正→存储**，全程 AgentLoop 加持。

> 当前处于 **Beta** 阶段——基本流程已跑通，内容质量把控和自动发布仍在持续优化中。

---

## 快速开始

```bash
# 1. 配置飞书凭证（详见下方「飞书接入」）
# 2. 启动
python3 -m conductor
```

在飞书里给机器人发消息即可触发，例如 `春天穿搭分享` 或 `深度：新品发布会`。

**不想用飞书？** 也可以用 CLI：

```bash
python3 -m conductor.cli --topic "春天穿搭分享" --platforms "小红书 抖音"
python3 -m conductor.cli --topic "新品发布会" --deep --brand mybrand
python3 -m conductor.cli --list           # 查看内容仓库
python3 -m conductor.cli --detail abc123  # 查看内容详情
```

---

## 两种模式

| 模式 | 说明 | 耗时 | 用法 |
|------|------|------|------|
| **快速模式** | LLM 直接产出创意 + 生成内容 | 1-3 分钟 | 直接发主题 |
| **深度模式** | 调用脑暴五人团队 + 规划引擎 + 生成内容 | 5-15 分钟 | `深度：主题` |

---

## 六阶段流水线

```
感知 → 构思 → 创作 → 发布 → 互动 → 复盘
```

| 阶段 | 模块 | 做什么 |
|------|------|--------|
| **感知** | `stages/trend_scanner.py` | 扫描各平台热点趋势 |
| **构思** | `stages/idea_engine.py` | 产出创意（快速模式用 LLM，深度模式调脑暴+规划） |
| **创作** | `stages/content_factory.py` | 生成文案 + 视觉 Prompt，质量不达标自动修改（最多 2 次） |
| **发布** | `stages/publisher.py` | 存入内容仓库，支持自动发布到平台 |
| **互动** | `stages/engager.py` | 监控评论 + 自动回复（开发中） |
| **复盘** | `stages/reviewer.py` | 效果分析 + 改进建议（开发中） |

---

## 内容管理命令（飞书）

```
草稿                        → 查看所有内容
详情 abc123                 → 查看完整内容（文案 + 视觉 Prompt）
发布 abc123                 → 审批通过，准备发布
定时 abc123 10:00           → 设置定时发布
删除 abc123                 → 删除内容
品牌 mybrand                → 切换品牌
平台 小红书 抖音            → 设置目标平台
人设 / 目标受众 / 内容目标  → 配置发帖策略
```

内容状态流转：`草稿(draft) → 待发布(ready) → 定时(scheduled) → 已发布(published)`

---

## 环境变量

**必填**（任选一组飞书凭证）：

| 变量 | 说明 |
|------|------|
| `CONDUCTOR_FEISHU_APP_ID` | 飞书应用 App ID（建议单独建应用） |
| `CONDUCTOR_FEISHU_APP_SECRET` | 飞书应用 App Secret |
| `DEEPSEEK_API_KEY` | 主力大模型 |

未配 `CONDUCTOR_*` 时会复用 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`。

**可选**：

| 变量 | 说明 |
|------|------|
| `DOUBAO_API_KEY` | 深度模式脑暴需要 |
| `KIMI_API_KEY` | 深度模式脑暴需要 |
| `CONDUCTOR_PERSONA_FILE` | 发帖人设文件路径 |
| `CONDUCTOR_SCHEDULE_ENABLED` | 启用定时选题+生成 |
| `CONDUCTOR_AUTO_PUBLISH` | 自动发布（默认 true） |
| `ARK_API_KEY` | Seedream/Seedance 图片/视频生成 |

完整变量列表见 [.env.example](../.env.example) 中 `自媒体助手` 区块。

---

## 详细文档

| 文档 | 内容 |
|------|------|
| [飞书接入说明](FEISHU_SETUP.md) | 从创建飞书应用到发第一条消息的完整步骤 |
| [人设与定时发布](PERSONA_AND_SCHEDULE.md) | 配置发帖人设、目标受众、定时选题生成 |
| [内容仓库](CONTENT_REPO.md) | 内容存储结构、状态机、CLI 管理 |
| [图片/视频生成](VOLCANO_QUICKSTART.md) | Seedream 图片 + Seedance 视频接入 |
| [端到端测试](E2E_TEST.md) | 从飞书消息到小红书发布的完整测试流程 |
| [休眠时定时发布](SCHEDULE_WHEN_SLEEP.md) | 电脑休眠时用外部 cron 触发定时任务 |

---

## AgentLoop 增强

自媒体助手在多个阶段使用 AgentLoop：
- **构思阶段**：自动搜索热点趋势和竞品案例
- **创作阶段**：写文案前查平台规范、文案框架、团队偏好
- **完成后**：生成「下一步：问对问题」卡片（需人判断的 + 可交给 AI 的 prompt）

团队判断力沉淀：设置品牌、人设、受众、内容目标时自动记录为团队决策，所有 bot 可复用。
