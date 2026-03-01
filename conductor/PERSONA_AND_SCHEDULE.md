# 发帖人设 / 目标 与 定时选题

## 一、自定义发帖人设和目标

你可以统一设定「发帖人设」「目标受众」「内容目标」，让生成的口吻和方向更符合预期。

### 在飞书里设置（推荐）

和自媒体助手对话时发送：

| 命令 | 说明 | 示例 |
|------|------|------|
| **人设** [描述] | 发帖口吻、风格、身份感 | 人设 治愈系旅行博主，语气温暖、爱用 emoji |
| **目标受众** [描述] | 目标受众是谁 | 目标受众 18-30岁一二线女性，喜欢生活方式与美妆 |
| **内容目标** [描述] | 做内容为了什么 | 内容目标 涨粉、种草、品牌曝光 |

只发「人设」「目标受众」「内容目标」不带内容时，会显示当前已设置的值。

### 用环境变量设默认值

在 `.env` 里配置后，新会话会默认带上这些值（飞书里仍可随时改）：

```bash
CONDUCTOR_PERSONA=治愈系旅行博主，语气温暖
CONDUCTOR_TARGET_AUDIENCE=18-30岁一二线女性
CONDUCTOR_CONTENT_GOALS=涨粉、种草、品牌曝光
```

这些会参与：**创意产出（Ideate）** 和 **文案生成（Create）**，不会改品牌或平台；品牌、平台仍用「品牌」「平台」命令或默认值。

---

## 二、定时选题 → 生成内容 → 审批或自动发布

开启「定时调度」后，程序会**每天在固定时间**自动：扫描热点 → 选一个选题 → 跑完整 Pipeline 生成内容，然后根据配置决定是「等你审批」还是「直接发布」。

### 1. 开启定时调度

在 `.env` 里设置：

```bash
CONDUCTOR_SCHEDULE_ENABLED=true
```

执行时间由 `.env` 里的 **CONDUCTOR_SCHEDULE_SCAN_TIMES** 决定，格式为逗号分隔的 `HH:MM`，例如：

```bash
CONDUCTOR_SCHEDULE_SCAN_TIMES=08:00,12:00,19:00
```

表示每天 8:00、12:00、19:00 各执行一次选题+生成。不配置时默认每天 08:00 执行一次。

### 2. 选题来源

- **不配置关键词**：用当天扫描到的**第一条热点**的标题作为选题。
- **配置关键词**：在 `.env` 里设置  
  `CONDUCTOR_SCHEDULE_TOPIC_KEYWORDS=咖啡,旅行,穿搭`  
  会从热点里优先选**标题包含任一关键词**的一条作为选题；没有匹配再用第一条热点。

### 3. 定时任务用的品牌与平台

```bash
CONDUCTOR_SCHEDULE_BRAND=sky
CONDUCTOR_SCHEDULE_PLATFORMS=xiaohongshu
```

人设/受众/目标若已在 `.env` 里配置 `CONDUCTOR_PERSONA`、`CONDUCTOR_TARGET_AUDIENCE`、`CONDUCTOR_CONTENT_GOALS`，定时任务会一并使用。

### 4. 需要审批时：飞书通知

若**没有**开 `CONDUCTOR_AUTO_PUBLISH`，生成的内容会先进入内容仓库，等你在飞书里审批或手动发布。  
若希望定时任务一生成就收到提醒，可配置**飞书群 Webhook**，有新内容待审批时推一张卡片到群：

```bash
CONDUCTOR_NOTIFY_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```

卡片里会带选题、标题、内容 ID，以及「详情 / 发布 / 自动发布」的简要说明。

### 5. 无需审批、直接发布

在 `.env` 里设置：

```bash
CONDUCTOR_AUTO_PUBLISH=true
```

则定时任务在生成内容后会**直接走发布逻辑**（例如发到小红书），不再等你审批。请确认账号、平台、风控都 OK 再开启。

### 6. 小结

| 目标 | 配置 |
|------|------|
| 每天定时选题并生成内容 | `CONDUCTOR_SCHEDULE_ENABLED=true` |
| 生成后等我审批再发 | 不设或 `CONDUCTOR_AUTO_PUBLISH=false`，可选 `CONDUCTOR_NOTIFY_WEBHOOK` 收通知 |
| 生成后自动发到平台 | `CONDUCTOR_AUTO_PUBLISH=true` |
| 选题偏向某类话题 | `CONDUCTOR_SCHEDULE_TOPIC_KEYWORDS=关键词1,关键词2` |

定时任务和你在飞书里手动发主题用的是同一套 Pipeline（创意 → 文案 → 发布），只是**选题**和**触发方式**不同：一个是定时自动扫热点选题，一个是你发一句话当主题。
