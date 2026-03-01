# 机器人 ↔ 飞书应用 ID 对照

各机器人的长连接与发消息都使用**同一套**飞书应用凭证；可单独为某机器人配置专用应用，未配则复用主凭证。

## 重要：同一 App ID 不要被多个机器人同时用

飞书按「应用」推事件：**同一个 App ID 的所有长连接都会收到同一份事件**。  
若脑暴和自媒体助手都使用 `FEISHU_APP_ID`（且未给自媒体助手单独配 `CONDUCTOR_FEISHU_APP_ID`），两个进程会**同时**连上同一个应用，用户打开该应用的会话时，**两个机器人都会发欢迎卡**，你可能会先看到「自媒体助手」那张。

**正确做法：**

- **脑暴**用的应用：只跑 `python3 -m brainstorm`，不要用同一 App ID 再跑自媒体助手。
- **自媒体助手**要用独立应用：在 .env 里配置 `CONDUCTOR_FEISHU_APP_ID` 和 `CONDUCTOR_FEISHU_APP_SECRET`（另一个飞书应用的凭证），再跑 `python3 -m conductor`。

这样「脑暴」会话里只会收到脑暴的欢迎卡，「自媒体助手」会话里只会收到自媒体助手的欢迎卡。

## 环境变量对照表

| 机器人 | 专用凭证（优先） | 回退凭证 | 发消息用哪个模块 |
|--------|------------------|----------|------------------|
| **脑暴** | 无 | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | core/feishu_client（读 `FEISHU_APP_ID`） |
| **规划** | `PLANNER_FEISHU_APP_ID` / `PLANNER_FEISHU_APP_SECRET` | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | core/feishu_client（启动时写入 env） |
| **助手** | `ASSISTANT_FEISHU_APP_ID` / `ASSISTANT_FEISHU_APP_SECRET` | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | core/feishu_client（启动时写入 env） |
| **创意** | `CREATIVE_FEISHU_APP_ID` / `CREATIVE_FEISHU_APP_SECRET` | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | core/feishu_client（启动时写入 env） |
| **舆情** | `SENTIMENT_FEISHU_APP_ID` / `SENTIMENT_FEISHU_APP_SECRET` | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | sentiment/feishu_api（独立读 env，已与 main 一致） |
| **自媒体助手** | `CONDUCTOR_FEISHU_APP_ID` / `CONDUCTOR_FEISHU_APP_SECRET` | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | core/feishu_client（启动时写入 env） |

## 配置要点

1. **只配一套时**：在 `.env` 里只填 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`，五个机器人都用这一套（每个机器人对应飞书开放平台里的**同一个应用**或各自应用看你怎么建）。
2. **某机器人用单独应用时**：为该机器人配上对应的 `XXX_FEISHU_APP_ID` 和 `XXX_FEISHU_APP_SECRET`，该机器人长连接和发消息都会用这套，其它机器人仍用主凭证（若未单独配）。
3. **舆情**：之前发消息用的 `sentiment/feishu_api` 只读 `SENTIMENT_*`，未配时不会回退到 `FEISHU_APP_ID`，已改为与 main 一致，未配 `SENTIMENT_*` 时回退到主凭证。

## 飞书开放平台侧

- 每个「应用」对应一个 App ID + App Secret。
- 若五个机器人共用一个应用：在同一个应用下配置「事件订阅 → 长连接」并订阅「接收消息 v2.0」即可；发消息时都用该应用的 token，ID 对。
- 若某机器人用单独应用：在开放平台再建一个应用，把该机器人的专用 `XXX_FEISHU_APP_ID` / `XXX_FEISHU_APP_SECRET` 填到 .env，确保该应用也开了长连接与接收消息。
