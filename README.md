# Awesome Lark Bots — 飞书 AI 机器人团队

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org)

**[English](#english)** | **中文**

一套在飞书（Lark）上运行的开源 AI 机器人，覆盖**创意脑暴、项目规划、日常助手、素材 Prompt 生成、舆情监控、新闻聚合、自媒体全流程编排**七大场景。

> **这是一个活跃探索中的项目。** 我们把它开源出来，是因为相信 AI + 飞书的自动化工作流有很大的想象空间，也希望有更多人一起来完善它。欢迎提 Issue、提 PR，或者单纯 star 一下表示支持。

### 为什么做这个？

我们相信 **不需要给 AI 完整的系统权限，也能让它帮你把大部分工作干了。**

- **日常自动化**（脑暴、规划、舆情采集、内容创作、定时发布……）→ 部署在云端，用**飞书聊天**作为交互入口，随时随地发条消息就能触发，轻量、安全、低权限
- **深度任务**（复杂架构设计、大规模代码重构……）→ 需要时再用 Claude Code 等重型工具，按需授权

大多数工作场景不需要把钥匙全交给 AI。一个聊天窗口 + 几个专注的机器人，够了。

---

## 最快体验路径

### 30 秒体验（不需要飞书）

`studio/` 是一个独立的 Streamlit 本地应用，**只需一个 API Key 就能跑**：

```bash
cd studio && streamlit run app.py
```

或者双击 `studio/启动工作站.command`（macOS）。支持灵感脑暴、规划、创作、调研四种模式，兼容所有 OpenAI 兼容 API。详见 [studio/README.md](studio/README.md)。

### 5 分钟跑一个 Bot（需要飞书）

```bash
pip3 install -r requirements.txt     # 1. 安装依赖（Python 3.11+）
cp .env.example .env                 # 2. 复制配置模板
                                     #    编辑 .env，填 3 个必填项：
                                     #    FEISHU_APP_ID + FEISHU_APP_SECRET + DEEPSEEK_API_KEY
python3 -m brainstorm                # 3. 启动（选任意一个 bot）
```

飞书应用怎么创建？→ **[飞书配置快速指南](docs/FEISHU_QUICKSTART.md)**

---

## 选择你的路径

**不确定该用哪个 bot？看看你想解决什么问题：**

| 你想… | 用这个 | 命令 |
|--------|--------|------|
| 快速体验，不想配飞书 | **Studio 工作站** | `cd studio && streamlit run app.py` |
| 一群 AI 帮你头脑风暴 | **脑暴机器人** | `python3 -m brainstorm` |
| 理性拆解一个复杂问题 | **规划机器人** | `python3 -m planner` |
| 管备忘、管项目、管钱、翻译 | **助手机器人** | `python3 -m assistant` |
| 生成 AI 图片/视频 Prompt | **素材 Bot** | `python3 -m creative` |
| 监控社交媒体舆论 | **舆情监控** | `python3 -m sentiment` |
| 每天收到一份新闻简报 | **早知天下事** | `python3 -m newsbot` |
| 从选题到发布全自动 | **自媒体助手** | `python3 -m conductor` |

> **建议**：第一次用？从**脑暴**或**规划**开始，体验最直观。想跑全流程内容生产？用**自媒体助手**，它会自动调用脑暴和规划。

---

## 七个机器人

### 脑暴机器人 (`brainstorm/`)

5 个 AI 角色（坚果五仁团队）四轮讨论：发散→具象→淘汰→交付。支持营销活动、创意项目、策略探讨、通用探索四种模式。AgentLoop 联网调研，飞书文档/Wiki 自动读取。

```
发消息：策略：增长靠补贴还是产品    → 启动策略讨论
发消息：粘贴飞书文档链接             → 自动读取内容作为背景
CLI：python3 -m brainstorm.run --topic "咖啡品牌 × 音乐节"
```

最终交付三板块：需要人判断的关键问题 + 可交给 AI 深化的 prompt + 视觉概念 prompt。

→ 详细用法见 [brainstorm/README.md](brainstorm/README.md)

### 规划机器人 (`planner/`)

六步结构化规划（问题定义→现状分析→方案生成→评估矩阵→执行计划→反馈机制），每步可联网搜索。完成后自动生成飞书云文档（10 种模板）。

```
发消息：规划：Q3 用户增长策略       → 启动六步规划
发消息：比稿：618 大促方案           → Agency 比稿模式（体验派/增长派/品牌派 PK）
发消息：粘贴飞书文档链接             → 读取内容作为规划背景
CLI：python3 -m planner.run --topic "Q3 策略"
```

→ 详细用法见 [planner/README.md](planner/README.md)

### 助手机器人 (`assistant/`)

全能工作搭档：备忘+工作线程（双向同步飞书看板）、项目管理（自动建 Bitable 六张表）、财务记账、双语翻译、联网研究、定时简报。

```
发消息：备忘 完成 deck #creator     → 记备忘并归入线程
发消息：创建项目 Q2营销             → 自动建多维表格
发消息：记账 午餐 35 #Q2营销        → 记账并同步 Bitable
发消息：翻译 我们希望在Q2完成优化    → 自动中→英
发消息：研究 Character.ai 增长机制  → 多来源交叉验证报告
```

自动推送：08:00 晨报 / 18:00 收尾 / 周一周报 / 月度报告。

→ 详细用法见 [assistant/README.md](assistant/README.md)

### 素材 Bot (`creative/`)

输入主题，生成 AI 图片/视频工具的结构化 Prompt。支持品牌切换、多轮讨论、一键安排制作（提交到飞书多维表格管理）。

```
发消息：春日樱花主题的抖音预告       → 立即出 prompt
发消息：聊聊：我想做一个关于重逢的视频 → 先讨论再出
发消息：安排制作                     → 生成执行 Brief → 提交素材管理表
```

输出：中文结构化 Prompt + Seedance 英文版 + 配套平台文案。超 15 秒需求自动分镜。

→ 详细用法见 [creative/README.md](creative/README.md)

### 舆情监控 (`sentiment/`)

三阶段采集流水线：JOA 全平台扫描 → 分平台深度搜索 → Web Search 补量（~1000 条）。覆盖 15+ 社媒平台。

```
发消息：周报                       → 默认品牌舆情周报
发消息：采集 咖啡品牌 @微博 @B站 7天 → 自定义采集
发消息：月报 +分析                  → 月报 + AI 分析报告
```

→ 详细用法见 [sentiment/README.md](sentiment/README.md)

### 早知天下事 (`newsbot/`)

多源新闻采集 + AI 分析，覆盖华人圈/亚太/欧美/全球热点。每日 08:00 自动推送，也可手动触发。

```
发消息：新闻                       → 今日新闻汇总
发消息：科技新闻                   → 按领域筛选
CLI：python3 -m newsbot --run      → 生成一次报告后退出
```

→ 详细用法见 [newsbot/README.md](newsbot/README.md)

### 自媒体助手 (`conductor/`) — Beta

端到端内容生产流水线：选题→脑暴→规划→创作→质量修正→存储→发布。自动调用脑暴和规划引擎。

```
发消息：春天穿搭分享               → 快速模式（1-3 分钟）
发消息：深度：新品发布会            → 深度模式（调脑暴+规划，5-15 分钟）
CLI：python3 -m conductor.cli --topic "主题" --platforms "小红书"
```

→ 详细用法见 [conductor/README.md](conductor/README.md)

---

七个机器人**共享底层模块**（LLM 调用、飞书 API、AgentLoop、技能系统、团队决策），各自独立运行、互不干扰。
**自媒体助手是总编排者**——它会自动调用脑暴、规划、创意 Prompt 等模块完成完整的内容生产流程。
**跨 Bot 联动**——每个 bot 完成任务后会引导你把结果带到其他 bot（如脑暴结论→规划细化→助理记待办），并生成「下一步：问对问题」卡片。

---

## 新手上路

### 第 1 步：安装依赖

```bash
# 需要 Python 3.11+
pip3 install -r requirements.txt
```

### 第 2 步：配置环境变量

```bash
cp .env.example .env
```

打开 `.env`，填入 **3 个必填项**：

| 变量 | 说明 | 去哪拿 |
|------|------|--------|
| `FEISHU_APP_ID` | 飞书应用 App ID | [飞书配置指南](docs/FEISHU_QUICKSTART.md) |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret | 同上 |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | [platform.deepseek.com](https://platform.deepseek.com) |

> **用脑暴机器人？** 额外需要 `DOUBAO_API_KEY` + `KIMI_API_KEY`（[为什么需要三个模型？](#llm-使用说明)）
> **用舆情监控？** 额外需要 `JOA_TOKEN`
> 完整变量说明见 [.env.example](.env.example)

> **同时跑多个 bot？** 每个 bot 需要不同的飞书应用 App ID，否则会同时收到消息。详见 [飞书凭证对照表](docs/FEISHU_APP_IDS.md)。

### 第 3 步：启动

```bash
python3 -m brainstorm    # 脑暴机器人
python3 -m planner       # 规划机器人
python3 -m assistant     # 助手机器人
python3 -m creative      # 素材 Bot
python3 -m sentiment     # 舆情监控
python3 -m newsbot       # 早知天下事
python3 -m conductor     # 自媒体助手
```

启动后在飞书给对应机器人发消息就能用了。

**不用飞书也能跑**——每个 bot 都有 CLI 模式：

```bash
python3 -m brainstorm.run --topic "咖啡品牌 × 音乐节"
python3 -m planner.run --topic "Q3 策略" --mode "快速模式"
python3 -m conductor.cli --topic "春天穿搭" --platforms "小红书"
python3 -m newsbot --run
```

---

## 核心概念

### AgentLoop — LLM 主动调用工具

所有机器人共享一个通用的 **AgentLoop 运行时**（`core/agent.py`），让 LLM 在生成过程中主动调用工具——搜索竞品、查平台规范、了解团队决策——而不是凭空编造信息。

```python
from core.agent import AgentLoop
from core.tools import WEB_SEARCH_TOOL, TRENDING_TOOL

agent = AgentLoop(provider="deepseek", system="你是内容策划师", max_rounds=5)
agent.add_tools([WEB_SEARCH_TOOL, TRENDING_TOOL])
result = agent.run("帮我找小红书最近的爆款话题")
```

**内置工具（`core/tools.py`）：**

| 工具 | 说明 |
|------|------|
| `web_search` | 联网搜索（Tavily + DuckDuckGo） |
| `news_search` | 新闻搜索 |
| `fetch_url` | 抓取网页内容 |
| `get_trending` | 平台热点趋势 |
| `search_platform` | 搜索指定平台内容 |
| `get_brand_info` | 查品牌知识 |
| `get_platform_guide` | 查平台运营规范 |
| `get_copywriting_framework` | 查文案框架（AIDA/PAS/FAB） |
| `get_team_decisions` | 查团队历史决策 |
| `get_user_context` | 查用户工作上下文（待办/项目） |

### 技能系统 (Skills)

所有机器人共享一套**可插拔的技能库**（`skills/`），通过 `core/skill_router.py` 自动路由——根据用户消息关键词和 bot 类型，自动将领域知识注入 system prompt。

```python
from core.skill_router import enrich_prompt
system = enrich_prompt("你是内容助手...", user_text=msg, bot_type="creative")
```

| 技能 | 说明 | 自动激活 |
|------|------|---------|
| `personal` | 个人工作风格与偏好 | 所有核心 bot |
| `decision_frameworks` | 第一性原理、pre-mortem、MECE 等 | planner |
| `stakeholder` | 利益相关方对齐 | planner（多方信号时） |
| `cross_cultural` | 跨文化策略 | planner（全球/海外信号时） |
| `translation` | 双语翻译（适配 PPT/邮件/Slack） | 关键词触发 |
| `team_decisions` | 团队判断力沉淀 | 所有 bot |
| `brand` | 品牌风格、调性、场景 | creative / conductor |
| `marketing` | 营销方法论 | planner / conductor |
| `platform` | 平台运营指南 | conductor / planner |
| `copywriting` | 经典文案框架 | conductor |
| `calendar` | 营销日历 | planner / conductor |

扩展新技能：在 `skills/` 下新建 `.py` 文件，继承 `Skill` 基类并 `register()` 即可。详见 [skills/README.md](skills/README.md)。

```bash
python3 -m skills list                      # 列出所有技能
python3 -m skills activate "帮我做品牌推广"   # 查看哪些技能会被激活
```

---

## LLM 使用说明

项目通过 `core/llm.py` 统一调用大模型，**兼容所有 OpenAI API 协议的服务商**。你可以自由替换为自己偏好的模型，只需在 `.env` 中修改对应的 API Key、Base URL 和模型名即可。

目前默认使用三家国产大模型，各有分工：

| 大模型 | 擅长 | 在哪用 |
|--------|------|--------|
| **DeepSeek** | 逻辑推理、结构化输出 | 规划全程、助手、脑暴策略角色、创意 Prompt |
| **豆包(Doubao)** | 创意发散 | 脑暴创意角色（核桃仁） |
| **Kimi** | 长文本理解 | 脑暴素材角色、最终交付物生成 |

> 这只是我们目前的组合。你完全可以换成 OpenAI、Claude、通义千问、智谱 GLM 或任何兼容 OpenAI 协议的模型——改 `.env` 里的三个变量就行。

---

## 项目结构

```
awesome-lark-bots/
│
├── core/                     # 共享核心模块（所有机器人都用）
│   ├── llm.py                #   大模型调用封装（支持 function calling）
│   ├── agent.py              #   AgentLoop 运行时（tool-calling 循环）
│   ├── tools.py              #   LLM 可调用工具库
│   ├── feishu_client.py      #   飞书 API（消息、日历、文档、Bitable、Wiki、Drive）
│   ├── doc_reader.py         #   飞书文档读取 + Kimi 长文摘要
│   ├── skill_router.py       #   技能路由器
│   └── utils.py              #   工具函数
│
├── brainstorm/               # 脑暴机器人 → README.md
├── planner/                  # 规划机器人 → README.md
├── assistant/                # 助手机器人 → README.md
├── creative/                 # 素材 Bot → README.md
├── sentiment/                # 舆情监控 → README.md
├── newsbot/                  # 早知天下事 → README.md
├── conductor/                # 自媒体助手 → README.md
│
├── pitch/                    # Agency 比稿模块（规划机器人使用）
├── memo/                     # 备忘+项目+财务（助手机器人使用）
├── cal/                      # 日程模块（助手机器人使用）
├── research/                 # 联网研究模块（助手机器人使用）
├── skills/                   # 共享技能库（11 个技能） → README.md
├── studio/                   # Streamlit 独立工作站 → README.md
├── claude_tasks/             # Claude Code 任务集成
│
├── CN-MKT-Skills/            # 营销技能知识库
├── data/                     # 数据目录（备忘、配置、Bitable 同步）
├── runs/                     # 运行记录输出（自动生成）
│
├── docker-compose.yml        # Docker 部署配置
├── .env.example              # 环境变量模板（分三层：必填/按需/高级）
├── requirements.txt          # Python 依赖
└── README.md                 # 本文件
```

---

## Docker 部署

```bash
# 启动所有机器人
docker-compose up -d

# 启动指定机器人
docker-compose up -d brainstorm planner

# 查看日志
docker-compose logs -f brainstorm
```

---

## 常见问题

**Q: 程序启动后提示连接失败？**
检查：1) App ID / App Secret 是否正确  2) 应用是否已发布  3) 网络是否能访问 open.feishu.cn。详见 [飞书配置指南](docs/FEISHU_QUICKSTART.md)。

**Q: 多个 bot 同时收到了消息？**
多个 bot 共用了同一个 App ID。同时运行多个 bot 时，需要为每个 bot 创建独立的飞书应用。详见 [飞书凭证对照表](docs/FEISHU_APP_IDS.md)。

**Q: 脑暴/规划结果在飞书群里看不到？**
确认 `FEISHU_WEBHOOK` 是否配置。结果通过 Webhook 推送到群，没配则只保存到本地 `runs/` 目录。

**Q: 助手的日程管理提示「权限不足」？**
往个人日历加日程需要用户身份授权。请在 `.env` 中配置 `FEISHU_TOKEN_CALENDAR_CREATE`。

**Q: 可以只运行其中一个机器人吗？**
可以。每个机器人完全独立，按需启动。最低只需 `FEISHU_APP_ID` + `FEISHU_APP_SECRET` + `DEEPSEEK_API_KEY`。

**Q: 运行记录保存在哪？**
`runs/` 文件夹，格式为 Markdown。

**Q: 不用飞书能跑吗？**
能。每个 bot 都有 CLI 模式（见上方[启动](#第-3-步启动)），或者用 [Studio 工作站](studio/README.md)。

---

## Roadmap

以下是我们正在探索和希望社区一起推进的方向：

### 自媒体助手（conductor）— 核心探索方向
- [x] **内容质量自动评估 + 自动修正**：质量不达标自动修改（最多 2 次），仍不达标保留供人工判断
- [x] **多平台内容适配**：AgentLoop 写文案前自动查平台规范、文案框架，适配各平台调性
- [x] **人机协作流程**：完成后生成 Handoff 卡片（需要人判断的 + 可交给 AI 的 prompt）
- [ ] **自媒体平台自动发布**：更稳定的方式把内容发布到小红书、抖音、微博等平台
- [ ] **数据驱动选题**：根据历史数据表现反馈，优化未来的内容选题方向

### 各模块改进
- [x] **跨 Bot 联动**：各 bot 完成后引导用户将结果带到其他 bot 继续推进
- [x] **AgentLoop**：所有核心 bot 支持 LLM 主动调用工具
- [x] **团队判断力沉淀**：团队偏好和决策自动记录并注入所有 bot 的 prompt
- [x] **飞书文档读取**：脑暴/规划支持粘贴飞书链接，长文档 Kimi 128K 摘要
- [x] **脑暴四种模式**：营销活动 / 创意项目 / 策略探讨 / 通用探索
- [ ] **脑暴**：支持自定义 AI 角色组合、更多大模型接入
- [ ] **舆情**：更多平台采集器、情感分析准确度提升
- [ ] **新闻聚合**：更多新闻源、可自定义的关注领域
- [ ] **创意 Prompt**：支持更多 AI 生成工具的 prompt 格式

### 基础设施
- [x] **错误处理和重试机制**：LLM 调用指数退避重试、AgentLoop 失败自动回退
- [ ] 单元测试覆盖核心模块
- [ ] 多语言支持（英文等）
- [ ] Web 管理面板（查看运行状态、管理内容）

欢迎在 [Issues](../../issues) 中讨论任何想法，或直接提 PR。

---

## 参与贡献

我们非常欢迎各种形式的贡献！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 许可证

[MIT License](LICENSE) — 你可以自由使用、修改和分发。

---

<a name="english"></a>

## English

### What is Awesome Lark Bots?

A collection of 7 open-source AI bots running on **Feishu (Lark)**, covering brainstorming, planning, daily assistance, creative prompt generation, social media monitoring, news aggregation, and end-to-end content creation workflows.

All bots are **compatible with any LLM that supports the OpenAI API protocol** — DeepSeek, OpenAI, Claude, Doubao, Kimi, Qwen, GLM, and more.

### Quickest Way to Try

**No Feishu? No problem.** The `studio/` folder is a standalone Streamlit app:

```bash
cd studio && streamlit run app.py
```

Four modes: Brainstorm (5 AI roles) · Plan (6-step) · Create (topic → storyboard) · Research (fact-checked). Works with any OpenAI-compatible API.

### Quick Start (with Feishu)

```bash
# 1. Install dependencies (Python 3.11+)
pip3 install -r requirements.txt

# 2. Configure environment variables
cp .env.example .env
# Edit .env — minimum: FEISHU_APP_ID + FEISHU_APP_SECRET + DEEPSEEK_API_KEY

# 3. Start any bot
python3 -m brainstorm    # Brainstorm bot
python3 -m planner       # Planner bot
python3 -m assistant     # Assistant bot
python3 -m creative      # Creative Prompt bot
python3 -m sentiment     # Sentiment Monitor
python3 -m newsbot       # News Digest
python3 -m conductor     # Content Assistant
```

### Which Bot Should I Use?

| I want to… | Use this | Command |
|------------|----------|---------|
| Quick try, no Feishu setup | **Studio** | `cd studio && streamlit run app.py` |
| AI team brainstorm | **Brainstorm** | `python3 -m brainstorm` |
| Break down a complex problem | **Planner** | `python3 -m planner` |
| Manage memos, projects, finances | **Assistant** | `python3 -m assistant` |
| Generate AI image/video prompts | **Creative** | `python3 -m creative` |
| Monitor social media sentiment | **Sentiment** | `python3 -m sentiment` |
| Daily news digest | **Newsbot** | `python3 -m newsbot` |
| End-to-end content pipeline | **Conductor** | `python3 -m conductor` |

### The 7 Bots

| Bot | What it does | Details |
|-----|-------------|---------|
| **Brainstorm** | 5 AI personas + AgentLoop research, 4 modes, Feishu doc reading | [README](brainstorm/README.md) |
| **Planner** | 6-step planning + Agency Pitch + Feishu doc delivery (10 templates) | [README](planner/README.md) |
| **Assistant** | Memos + Bitable sync, project management, finance, translation, research | [README](assistant/README.md) |
| **Creative** | AI tool prompt generation + exec brief → Bitable asset tracker | [README](creative/README.md) |
| **Sentiment** | 3-phase pipeline: 15 social platforms + Web Search (~1000 posts) | [README](sentiment/README.md) |
| **Newsbot** | Multi-source news aggregation + AI analysis, daily push | [README](newsbot/README.md) |
| **Conductor** (Beta) | End-to-end content pipeline with auto quality revision | [README](conductor/README.md) |

### Feishu (Lark) Setup

1. Go to [Feishu Open Platform](https://open.feishu.cn/app) and create an app
2. Get the **App ID** and **App Secret**, put them in `.env`
3. Enable **Bot** capability, subscribe to **Receive Message v2.0** event
4. Choose **Long Connection (WebSocket)** mode — no public URL needed
5. Publish the app, run the bot, send it a message

**Running multiple bots:** Give each a separate App ID. See [docs/FEISHU_APP_IDS.md](docs/FEISHU_APP_IDS.md).

### LLM Compatibility

Uses the OpenAI-compatible API protocol. Swap any provider by changing `*_API_KEY`, `*_BASE_URL`, `*_MODEL` in `.env`.

### Core Concepts

- **AgentLoop** (`core/agent.py`): Tool-calling runtime for all bots. Built-in tools: `web_search`, `news_search`, `fetch_url`, `get_trending`, `search_platform`, `get_brand_info`, `get_platform_guide`, `get_copywriting_framework`, `get_team_decisions`, `get_user_context`.
- **Skills System** (`skills/`): Auto-routed domain knowledge injection. 11 built-in skills. Add custom skills by extending `Skill` base class. See [skills/README.md](skills/README.md).
- **Team Decisions**: Preferences and decisions made in any bot are automatically recorded and injected into all bots' prompts.

### Contributing

We welcome all contributions! See [CONTRIBUTING.md](CONTRIBUTING.md).

### License

[MIT License](LICENSE)
