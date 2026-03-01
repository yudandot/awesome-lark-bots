# 自媒体助手机器人 — 飞书接入说明

自媒体助手通过**飞书长连接（WebSocket）** 收消息，不需要公网 URL，只需在飞书开放平台创建应用并拿到 **App ID** 和 **App Secret** 即可。

---

## 一、需要你提供的内容

在 `.env` 里配置下面两个变量（二选一）：

| 变量 | 说明 |
|------|------|
| `CONDUCTOR_FEISHU_APP_ID` | 飞书应用的 **App ID**（如 `cli_a1b2c3d4e5f6`） |
| `CONDUCTOR_FEISHU_APP_SECRET` | 飞书应用的 **App Secret** |

如果已经为其他机器人配过主凭证，也可以**不单独配**，直接复用：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

自媒体助手会优先用 `CONDUCTOR_*`，没有再用 `FEISHU_*`。

---

## 二、在飞书开放平台创建/配置应用

### 1. 打开飞书开放平台

- 地址：<https://open.feishu.cn/app>
- 用飞书账号登录（需有创建应用权限）

### 2. 创建应用（或选已有应用）

- 点击「创建企业自建应用」
- 填写名称（如「自媒体助手」）、描述，选择可见范围（建议选「全部」或指定部门）
- 创建后进入应用详情

### 3. 拿到 App ID 和 App Secret

- 在应用详情页左侧点「凭证与基础信息」
- **App ID**：形如 `cli_xxxxxxxxxx`
- **App Secret**：点击「显示」后复制

把这两个值填进项目根目录的 `.env`：

```bash
# 自媒体助手专用（或与其它机器人共用下面两个）
CONDUCTOR_FEISHU_APP_ID=cli_你的AppID
CONDUCTOR_FEISHU_APP_SECRET=你的AppSecret
```

### 4. 开启机器人能力

- 左侧进入「机器人」→「机器人配置」
- 勾选「启用机器人」
- 能力与权限里勾选：
  - **接收消息**（接收用户发给机器人的消息）
  - **发送消息**（机器人回复用户）
- 如需要群聊：勾选「群聊中 @ 机器人」
- 保存

### 5. 配置事件订阅（长连接）

- 左侧进入「事件订阅」
- 选择 **「长连接」** 模式（不是「Webhook」）
- 无需填写请求地址；程序会主动连飞书，飞书通过长连接把事件推下来

订阅事件建议至少包含（与代码中注册一致）：

- `im.message.receive_v1` — 接收消息
- `im.chat.access_event.bot_p2p_chat_entered_v1` — 用户打开与机器人的单聊（用于发欢迎语）
- `im.message.message_read_v1` — 消息已读（可选）

### 6. 权限

在「权限管理」中确保应用拥有：

- `im:message` — 发消息
- `im:message.group_at_msg` — 群内 @ 消息（若用群聊）
- 接收消息相关权限由「机器人」配置里的「接收消息」控制

保存后如有「申请权限」提示，按流程申请并等待管理员通过。

### 7. 发布与可用范围

- 「版本管理与发布」→ 创建版本 → 提交审核（或仅企业内使用则直接发布）
- 确保使用机器人的飞书用户在该应用的「可用范围」内

---

## 三、本地启动

```bash
# 在项目根目录
cp .env.example .env
# 编辑 .env，填上 CONDUCTOR_FEISHU_APP_ID 和 CONDUCTOR_FEISHU_APP_SECRET（或 FEISHU_APP_ID / FEISHU_APP_SECRET）

python3 -m conductor
```

看到类似输出即表示已连上飞书：

```
============================================================
AIlarkteams 自媒体助手（长连接模式）
...
正在连接飞书… (第 1 次)
```

在飞书里找到该应用，打开与机器人的单聊，发消息（例如「春天穿搭」或「帮助」）即可测试。

---

## 四、常见问题

- **提示「请设置环境变量 CONDUCTOR_FEISHU_APP_ID / CONDUCTOR_FEISHU_APP_SECRET」**  
  说明 `.env` 里没有配置；按上面第二节填好并保存后重启 `python3 -m conductor`。

- **连接失败 / 收不到消息**  
  检查：App ID / Secret 是否复制完整、应用是否已发布、是否开启了「机器人」且勾选「接收消息」「发送消息」、当前飞书账号是否在应用可用范围内。

- **想和脑暴/创意 prompt 等共用一个应用**  
  只配 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`，不配 `CONDUCTOR_*` 即可，自媒体助手会复用这两个变量。
