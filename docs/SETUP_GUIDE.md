# AIlarkteam 安装配置指南 — 从零开始，一步不漏

> 面向完全没有配置过的同事。跟着做就行，不需要理解原理。
>
> 预计耗时：首次配置 20-30 分钟，后续启动 30 秒。

---

## 目录

- [你需要准备什么](#你需要准备什么)
- [第一步：安装 Python](#第一步安装-python)
- [第二步：下载项目代码](#第二步下载项目代码)
- [第三步：安装项目依赖](#第三步安装项目依赖)
- [第四步：申请 AI 模型的 API Key](#第四步申请-ai-模型的-api-key)
- [第五步：在飞书上创建机器人应用](#第五步在飞书上创建机器人应用)
- [第六步：配置环境变量](#第六步配置环境变量)
- [第七步：启动机器人](#第七步启动机器人)
- [验证：确认一切正常](#验证确认一切正常)
- [进阶：同时运行多个机器人](#进阶同时运行多个机器人)
- [进阶：Docker 一键部署](#进阶docker-一键部署)
- [出了问题？](#出了问题)

---

## 你需要准备什么

| 需要什么 | 为什么需要 | 大概多久 |
|---------|-----------|---------|
| 一台电脑（Mac / Windows / Linux 都行） | 运行机器人 | — |
| Python 3.11 或更高版本 | 机器人用 Python 写的 | 5 分钟 |
| 飞书账号 + 管理员权限（或有人帮你审批） | 创建飞书机器人应用 | — |
| DeepSeek API Key | 主力 AI 模型 | 3 分钟 |
| （可选）豆包 API Key + Kimi API Key | 脑暴机器人需要 | 各 3 分钟 |

**费用：** 项目本身免费。AI 模型按量付费，DeepSeek 约 ¥0.01/次对话，一次完整脑暴约 ¥0.2-0.5。各平台新注册通常都有免费额度。

---

## 第一步：安装 Python

> 如果你已经有 Python 3.11+，跳过这一步。

### 检查是否已安装

打开终端（Mac 用「终端」app，Windows 用「命令提示符」或「PowerShell」），输入：

```bash
python3 --version
```

如果显示 `Python 3.11.x` 或更高版本，说明已安装，跳过这一步。

如果提示「找不到命令」或版本太低，按下面的方式安装：

### Mac

```bash
# 方式一：用 Homebrew（推荐）
brew install python@3.11

# 方式二：去 Python 官网下载安装包
# https://www.python.org/downloads/
```

### Windows

1. 打开 https://www.python.org/downloads/
2. 下载最新版 Python（3.11 或更高）
3. 运行安装程序，**一定要勾选 "Add Python to PATH"**
4. 安装完成后重新打开命令提示符，输入 `python --version` 验证

> Windows 上可能需要用 `python` 而不是 `python3`，后面的命令里自行替换。

### Linux (Ubuntu/Debian)

```bash
sudo apt update && sudo apt install python3.11 python3-pip -y
```

---

## 第二步：下载项目代码

### 方式一：用 Git（推荐）

```bash
git clone https://github.com/yudandot/AIlarkteam.git
cd AIlarkteam
```

> 如果没有 Git：
> - Mac: `brew install git`
> - Windows: 去 https://git-scm.com 下载安装
> - Linux: `sudo apt install git`

### 方式二：直接下载 ZIP

1. 打开项目 GitHub 页面
2. 点绿色的 「Code」 按钮 → 「Download ZIP」
3. 解压到你想放的位置
4. 用终端进入解压后的目录：
   ```bash
   cd ~/Downloads/AIlarkteam-main    # 路径根据你解压的位置调整
   ```

---

## 第三步：安装项目依赖

在项目目录下运行：

```bash
pip3 install -r requirements.txt
```

> 如果提示权限问题，加 `--user`：
> ```bash
> pip3 install --user -r requirements.txt
> ```

等它跑完，看到一堆 `Successfully installed ...` 就行了。

### 常见问题

**提示 `pip3: command not found`**
- 试试 `pip install -r requirements.txt`（不带 3）
- 或者 `python3 -m pip install -r requirements.txt`

**安装很慢**
- 用国内镜像加速：
  ```bash
  pip3 install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  ```

---

## 第四步：申请 AI 模型的 API Key

### 4.1 DeepSeek API Key（必须）

这是主力模型，所有机器人都需要。

1. 打开 https://platform.deepseek.com
2. 注册/登录账号
3. 左侧菜单点「API Keys」
4. 点「创建 API Key」
5. 复制生成的 Key（形如 `sk-xxxxxxxxxxxxxxxx`）
6. **找个地方先保存好**，后面要用

> DeepSeek 新用户有免费额度，日常使用非常便宜。

### 4.2 豆包 API Key（脑暴机器人需要，其他机器人不需要）

豆包是字节跳动的模型，用于脑暴中的创意角色。

1. 打开 https://console.volcengine.com
2. 注册/登录火山引擎账号
3. 搜索进入「方舟大模型」（Ark）
4. 创建一个「推理接入点」：
   - 模型选 `doubao-1.5-pro-32k`（或你想用的模型）
   - 创建后你会得到一个「接入点 ID」（形如 `ep-xxxxxxxxxx`）
5. 去「API Key 管理」创建一个 Key
6. **记录三样东西：** API Key、接入点 ID（就是模型名）、API 地址 `https://ark.cn-beijing.volces.com/api/v3`

### 4.3 Kimi API Key（脑暴机器人需要，其他机器人不需要）

Kimi 是月之暗面的模型，用于脑暴中的体验/素材角色。

1. 打开 https://platform.moonshot.cn
2. 注册/登录账号
3. 「API Key 管理」→ 创建 Key
4. 复制 Key（形如 `sk-xxxxxxxx`）

### 4.4 JustOneAPI Token（舆情监控机器人需要）

用于从社交媒体平台采集数据，需要找管理员获取 JOA 服务的 Token 和地址。

### 先跑起来再说

**如果你只想先体验一下，只需要 DeepSeek 一个 Key 就够了。** 规划、助手、创意 Prompt、自媒体助手（快速模式）都只需要 DeepSeek。脑暴机器人需要三个 Key。

---

## 第五步：在飞书上创建机器人应用

这一步是让你的程序能连上飞书、收发消息。

### 5.1 创建应用

1. 用浏览器打开 https://open.feishu.cn/app
2. 用你的飞书账号登录
3. 点右上角「创建企业自建应用」

   ![创建应用](https://open.feishu.cn 的截图——实际操作时跟着页面走即可)

4. 填写：
   - **应用名称：** 起个名字，比如「AI 助手」或「脑暴机器人」
   - **应用描述：** 随便写，比如「AI 工作流机器人」
5. 点「确定创建」

### 5.2 获取凭证

1. 进入应用详情页
2. 左侧菜单点「凭证与基础信息」
3. 你会看到：
   - **App ID：** 形如 `cli_a1b2c3d4e5f6`
   - **App Secret：** 点「显示」后复制
4. **把这两个值保存好**，后面要用

### 5.3 启用机器人能力

1. 左侧菜单点「应用能力」→「机器人」
2. 点「启用机器人」开关
3. 勾选：
   - ✅ 接收消息
   - ✅ 发送消息

### 5.4 配置事件订阅（关键步骤）

1. 左侧菜单点「开发配置」→「事件与回调」
2. **请求方式选「长连接」**（不是「将事件发送至开发者服务器」）

   > 选「长连接」意味着你不需要公网 IP、不需要买服务器域名。程序会主动连飞书。

3. 点「添加事件」，搜索并添加：
   - `im.message.receive_v1`（接收消息）— **必须**
   - `im.chat.access_event.bot_p2p_chat_entered_v1`（用户打开对话）— 推荐，用于发欢迎语
   - `im.message.message_read_v1`（消息已读）— 可选

### 5.5 配置权限

1. 左侧菜单「权限管理」
2. 搜索并开通以下权限：
   - `im:message` — 获取与发送单聊、群聊消息
   - `im:message:send_as_bot` — 以应用的身份发送消息
3. 如果需要管理员审批，提交申请后等审批通过

### 5.6 发布应用

1. 左侧菜单「版本管理与发布」
2. 点「创建版本」
3. 填写版本号（如 `1.0.0`）和更新说明
4. 点「发布」（如果是企业内部使用，选「企业内发布」）
5. 设置「可用范围」— 选「全部成员」或指定部门/人员

> 发布成功后，在飞书的搜索栏搜你的应用名，就能找到机器人。

### 要不要建多个应用？

- **先跑一个就够了：** 多个机器人可以共用一个飞书应用
- **如果同时运行多个机器人：** 建议每个机器人单独建一个应用，避免消息串台

---

## 第六步：配置环境变量

### 6.1 创建配置文件

```bash
cp .env.example .env
```

这会复制一份配置模板。接下来编辑 `.env` 文件：

```bash
# Mac / Linux
nano .env          # 或用 vim、VS Code 等任何编辑器

# Windows
notepad .env       # 或用 VS Code
```

### 6.2 填入你的配置

把文件里的 `xxx` 和占位符替换成你自己的值。**以下是最小配置（只需要改 3 行）：**

```bash
# ─── 最小配置（3 行就能跑）───────────────────────
FEISHU_APP_ID=cli_你的AppID
FEISHU_APP_SECRET=你的AppSecret
DEEPSEEK_API_KEY=sk-你的DeepSeekKey
```

保存文件。

### 6.3 如果你要用脑暴机器人，还需要加这几行

```bash
# ─── 脑暴机器人额外需要 ─────────────────────────
DOUBAO_API_KEY=你的豆包Key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=ep-你的接入点ID

KIMI_API_KEY=你的KimiKey
```

### 6.4 如果你要用舆情监控，还需要

```bash
# ─── 舆情监控额外需要 ──────────────────────────
JOA_TOKEN=你的JOA_Token
# JOA_BASE_URL=http://你的JOA服务地址:30015
```

### 6.5 可选但推荐：飞书群 Webhook

脑暴/规划的讨论过程可以实时推送到飞书群，方便所有人围观。

获取方式：
1. 打开一个飞书群
2. 群设置 → 群机器人 → 添加机器人
3. 选「自定义机器人」
4. 起个名字，复制 Webhook 地址

```bash
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook地址
```

### 完整配置对照表

| 变量 | 必填？ | 谁需要 | 从哪获取 |
|------|--------|--------|---------|
| `FEISHU_APP_ID` | **必填** | 所有机器人 | 飞书开放平台 → 应用 → 凭证 |
| `FEISHU_APP_SECRET` | **必填** | 所有机器人 | 同上 |
| `DEEPSEEK_API_KEY` | **必填** | 所有机器人 | platform.deepseek.com → API Keys |
| `DOUBAO_API_KEY` | 脑暴必填 | 脑暴机器人 | console.volcengine.com → 方舟 → API Key |
| `DOUBAO_MODEL` | 脑暴必填 | 脑暴机器人 | 火山方舟 → 推理接入点 → 接入点 ID |
| `KIMI_API_KEY` | 脑暴必填 | 脑暴机器人 | platform.moonshot.cn → API Key |
| `JOA_TOKEN` | 舆情必填 | 舆情监控 | 找管理员获取 |
| `FEISHU_WEBHOOK` | 推荐 | 脑暴/规划 | 飞书群 → 群机器人 → 自定义机器人 |

---

## 第七步：启动机器人

### 启动单个机器人

```bash
# 在项目目录下运行（选一个）
python3 -m brainstorm    # 脑暴机器人
python3 -m planner       # 规划机器人
python3 -m assistant     # 助手机器人
python3 -m creative      # 创意 Prompt 机器人
python3 -m sentiment     # 舆情监控机器人
python3 -m newsbot       # 早知天下事
python3 -m conductor     # 自媒体助手
```

### 看到什么说明成功了

终端会打印类似这样的日志：

```
============================================================
AIlarkteams 脑暴机器人（长连接模式）
============================================================
  App ID  : cli_a1b2xxxxx
  Webhook : https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
============================================================
正在连接飞书… (第 1 次)
```

**看到「正在连接飞书」且没有报错，说明启动成功。**

### 保持程序运行

启动后这个终端窗口要**保持打开**，关掉窗口程序就停了。

如果想在后台运行：
```bash
# Linux / Mac
nohup python3 -m brainstorm > brainstorm.log 2>&1 &

# 查看日志
tail -f brainstorm.log
```

---

## 验证：确认一切正常

1. 打开飞书
2. 搜索你创建的机器人应用名
3. 打开与机器人的对话
4. 发一条消息测试

### 测试各机器人

| 机器人 | 发什么测试 | 期望看到 |
|--------|-----------|---------|
| 脑暴 | `咖啡品牌 × 音乐节` | 收到进度卡片，飞书群开始收到讨论消息 |
| 规划 | `Q3 用户增长策略` | 收到进度卡片，1-2 分钟后收到规划结果 |
| 助手 | `备忘 买牛奶` | 收到"已记录"反馈 |
| 创意 Prompt | `春日樱花的抖音预告` | 收到完整的视觉 Prompt |
| 舆情 | `周报` | 开始采集数据（需要配了 JOA_TOKEN） |
| 自媒体助手 | `春天穿搭分享` | 收到模式选择卡片（快速/深度） |

---

## 进阶：同时运行多个机器人

### 方法一：多开终端窗口

最简单的方式——每个终端窗口启动一个：

```bash
# 终端窗口 1
python3 -m brainstorm

# 终端窗口 2
python3 -m planner

# 终端窗口 3
python3 -m assistant
```

### 方法二：后台运行（推荐）

```bash
# 一次性启动多个，都在后台运行
nohup python3 -m brainstorm > logs/brainstorm.log 2>&1 &
nohup python3 -m planner > logs/planner.log 2>&1 &
nohup python3 -m assistant > logs/assistant.log 2>&1 &
nohup python3 -m creative > logs/creative.log 2>&1 &

# 查看谁在运行
ps aux | grep "python3 -m"

# 停止某个机器人
kill <进程号>
```

> 先建好 logs 目录：`mkdir -p logs`

### 方法三：用一个脚本一键启动

创建 `start_all.sh`：

```bash
#!/bin/bash
mkdir -p logs

echo "启动脑暴机器人..."
nohup python3 -m brainstorm > logs/brainstorm.log 2>&1 &

echo "启动规划机器人..."
nohup python3 -m planner > logs/planner.log 2>&1 &

echo "启动助手机器人..."
nohup python3 -m assistant > logs/assistant.log 2>&1 &

echo "启动创意 Prompt..."
nohup python3 -m creative > logs/creative.log 2>&1 &

echo "全部启动完成！查看日志：tail -f logs/*.log"
```

```bash
chmod +x start_all.sh
./start_all.sh
```

### 多个机器人共用一个飞书应用 vs 各自独立

| 方案 | 优点 | 缺点 |
|------|------|------|
| 共用一个应用 | 配置简单，只需一套 App ID/Secret | 所有机器人消息走同一入口，可能串台 |
| 每个独立应用 | 互不干扰，用户在飞书上看到不同的机器人头像和名字 | 要创建多个应用，配置多套凭证 |

**建议：** 先用一个应用跑通，觉得好用了再拆。`.env` 里支持给每个机器人配独立凭证：

```bash
# 脑暴专用
FEISHU_APP_ID=cli_脑暴的AppID
FEISHU_APP_SECRET=脑暴的Secret

# 规划专用
PLANNER_FEISHU_APP_ID=cli_规划的AppID
PLANNER_FEISHU_APP_SECRET=规划的Secret

# 助手专用
ASSISTANT_FEISHU_APP_ID=cli_助手的AppID
ASSISTANT_FEISHU_APP_SECRET=助手的Secret

# 创意 Prompt 专用
CREATIVE_FEISHU_APP_ID=cli_创意的AppID
CREATIVE_FEISHU_APP_SECRET=创意的Secret

# 自媒体助手专用
CONDUCTOR_FEISHU_APP_ID=cli_自媒体的AppID
CONDUCTOR_FEISHU_APP_SECRET=自媒体的Secret
```

---

## 进阶：Docker 一键部署

如果你熟悉 Docker，可以用 docker-compose 一键启动所有机器人：

### 前提

- 安装了 Docker 和 docker-compose
- `.env` 文件已配置好

### 启动

```bash
# 启动所有机器人
docker-compose up -d

# 或者只启动你需要的
docker-compose up -d brainstorm planner assistant

# 查看运行状态
docker-compose ps

# 查看某个机器人的日志
docker-compose logs -f brainstorm

# 停止所有
docker-compose down
```

Docker 的好处：
- 不需要手动安装 Python 和依赖
- 自动重启（程序崩溃后会自动拉起来）
- 环境隔离，不影响你电脑上的其他东西

---

## 出了问题？

### 启动时报错

| 报错信息 | 原因 | 解决 |
|---------|------|------|
| `ModuleNotFoundError: No module named 'xxx'` | 依赖没装全 | `pip3 install -r requirements.txt` |
| `请设置环境变量 FEISHU_APP_ID` | `.env` 没配好 | 检查 `.env` 文件是否在项目根目录，值是否填了 |
| `请设置环境变量 DEEPSEEK_API_KEY` | DeepSeek Key 没填 | 检查 `.env` 中 `DEEPSEEK_API_KEY` 是否正确 |
| `Connection refused` / `连接失败` | 飞书应用没发布，或 App ID/Secret 错了 | 检查飞书应用是否已发布、凭证是否正确 |
| `Invalid API key` | AI 模型 Key 错了或过期 | 去对应平台重新生成 Key |

### 启动成功但飞书收不到回复

1. **检查应用是否已发布：** 飞书开放平台 → 你的应用 → 版本管理 → 确认已发布
2. **检查可用范围：** 确认你的飞书账号在应用的「可用范围」内
3. **检查事件订阅：** 确认添加了 `im.message.receive_v1` 事件，且选了「长连接」模式
4. **检查终端日志：** 看看有没有报错信息

### 脑暴机器人启动但讨论没推到飞书群

- 检查 `.env` 中 `FEISHU_WEBHOOK` 是否配了
- 检查 Webhook URL 是否正确（在飞书群 → 群设置 → 群机器人 里查看）

### 程序断开了

所有机器人都有自动重连机制，网络恢复后会自动重连。如果长时间连不上：
1. 检查网络是否正常
2. 终端里按 Ctrl+C 停止程序
3. 重新运行启动命令

### 还是不行？

1. 看终端的完整报错信息
2. 去项目 GitHub 的 Issues 页面搜索类似问题
3. 提一个新 Issue，附上报错信息和你的配置（**注意隐藏 Key/Secret 等敏感信息**）

---

## 快速参考卡片

把这张表打印出来或截图保存，以后忘了看一眼就行：

```
┌─────────────────────────────────────────────────┐
│            AIlarkteam 快速参考                    │
├─────────────────────────────────────────────────┤
│                                                  │
│  启动命令（在项目目录下运行）：                       │
│                                                  │
│    python3 -m brainstorm   → 脑暴机器人           │
│    python3 -m planner      → 规划机器人           │
│    python3 -m assistant    → 助手机器人           │
│    python3 -m creative     → 创意 Prompt          │
│    python3 -m sentiment    → 舆情监控             │
│    python3 -m newsbot      → 早知天下事           │
│    python3 -m conductor    → 自媒体助手           │
│                                                  │
│  最少需要配 3 个变量：                              │
│    FEISHU_APP_ID + FEISHU_APP_SECRET              │
│    + DEEPSEEK_API_KEY                             │
│                                                  │
│  脑暴额外需要：                                    │
│    DOUBAO_API_KEY + DOUBAO_MODEL + KIMI_API_KEY   │
│                                                  │
│  配置文件：项目根目录的 .env                         │
│  运行日志：终端窗口里看 / logs/ 目录                  │
│  运行记录：runs/ 目录                              │
│                                                  │
│  停止：Ctrl+C                                     │
│  重启：重新运行启动命令                              │
│                                                  │
└─────────────────────────────────────────────────┘
```
