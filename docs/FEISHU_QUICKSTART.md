# 飞书配置快速指南

从零开始，让你的第一个机器人在飞书上跑起来。全程约 10 分钟。

---

## 第 1 步：创建飞书应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app)，用飞书账号登录
2. 点击 **「创建企业自建应用」**
3. 填写应用名称（如「AI 脑暴」）和描述
4. 创建完成后，进入应用详情页

---

## 第 2 步：拿到凭证

在应用详情页左侧点 **「凭证与基础信息」**：

- **App ID**：形如 `cli_xxxxxxxxxx`
- **App Secret**：点击「显示」后复制

把这两个值填进项目根目录的 `.env`：

```bash
FEISHU_APP_ID=cli_你的AppID
FEISHU_APP_SECRET=你的AppSecret
```

---

## 第 3 步：开启机器人能力

在应用详情页左侧：

1. 进入 **「机器人」→「机器人配置」**
2. 勾选 **「启用机器人」**
3. 在能力与权限里勾选：
   - **接收消息** — 接收用户发给机器人的消息
   - **发送消息** — 机器人回复用户
4. 保存

---

## 第 4 步：配置事件订阅（长连接）

1. 左侧进入 **「事件订阅」**
2. 选择 **「长连接」模式**（不是「Webhook」）— 无需公网 URL
3. 添加以下事件：
   - `im.message.receive_v1` — 接收消息（**必须**）
   - `im.chat.access_event.bot_p2p_chat_entered_v1` — 用户打开单聊时发欢迎语（推荐）
   - `im.message.message_read_v1` — 消息已读（可选）

---

## 第 5 步：配置权限

在 **「权限管理」** 中确保应用拥有：

| 权限 | 用途 |
|------|------|
| `im:message` | 发送消息 |
| `im:message.group_at_msg` | 群内 @消息（群聊场景） |

如果要用**飞书文档/多维表格**功能（规划文档交付、助手项目管理等），还需开通：

| 权限 | 用途 |
|------|------|
| `docx:document` | 创建/编辑云文档 |
| `sheets:spreadsheet` | 创建/编辑电子表格 |
| `bitable:app` | 创建/编辑多维表格 |
| `drive:drive:permission:member` | 分享文档给用户 |

> 保存后如有「申请权限」提示，按流程申请并等管理员通过。

---

## 第 6 步：发布应用

1. 左侧进入 **「版本管理与发布」**
2. 创建版本 → 提交审核（企业内使用可直接发布）
3. 确保你的飞书账号在应用的 **「可用范围」** 内

---

## 第 7 步：启动机器人

```bash
# 安装依赖
pip3 install -r requirements.txt

# 启动（选一个）
python3 -m brainstorm    # 脑暴
python3 -m planner       # 规划
python3 -m assistant     # 助手
python3 -m creative      # 素材
python3 -m sentiment     # 舆情
python3 -m newsbot       # 新闻
python3 -m conductor     # 自媒体助手
```

看到类似输出即表示连接成功：

```
============================================================
AIlarkteams 脑暴机器人（长连接模式）
...
正在连接飞书… (第 1 次)
```

在飞书里找到对应机器人，发一条消息试试。

---

## 同时跑多个机器人

> **关键规则：同时运行多个机器人时，每个 bot 要用不同的飞书应用（不同的 App ID）。**
>
> 原因：飞书按应用推事件，同一个 App ID 的所有长连接都会收到同一份消息，导致多个 bot 同时响应。

**只跑 1-2 个**：共用一套凭证即可。

**同时跑多个**：为每个 bot 在飞书开放平台创建独立应用，然后在 `.env` 中配置专用凭证：

```bash
# 脑暴（使用主凭证）
FEISHU_APP_ID=cli_brainstorm_app
FEISHU_APP_SECRET=secret1

# 规划（专用凭证）
PLANNER_FEISHU_APP_ID=cli_planner_app
PLANNER_FEISHU_APP_SECRET=secret2

# 助手（专用凭证）
ASSISTANT_FEISHU_APP_ID=cli_assistant_app
ASSISTANT_FEISHU_APP_SECRET=secret3

# ... 以此类推
```

每个 bot 优先使用自己的 `XXX_FEISHU_APP_ID`，没配则回退到主凭证 `FEISHU_APP_ID`。

完整对照表见 [docs/FEISHU_APP_IDS.md](FEISHU_APP_IDS.md)。

---

## 常见问题

**连接失败 / 收不到消息**
- App ID / Secret 是否复制完整？
- 应用是否已发布？
- 是否开启了「机器人」且勾选「接收消息」「发送消息」？
- 你的飞书账号是否在应用「可用范围」内？
- 事件订阅是否选了「长连接」模式并添加了 `im.message.receive_v1`？

**多个 bot 同时收到消息**
- 检查是否共用了同一个 App ID，需要为每个 bot 创建独立应用

**群聊中机器人没反应**
- 需要 @机器人 才会触发
- 确认应用权限中包含 `im:message.group_at_msg`

**Webhook 推送不到群**
- 检查 `FEISHU_WEBHOOK` 是否填写正确
- Webhook 地址在飞书群 → 设置 → 群机器人 → 添加「自定义机器人」→ 复制地址
