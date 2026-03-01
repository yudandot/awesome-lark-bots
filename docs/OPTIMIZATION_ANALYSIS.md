# AIlarkteam 优化方向与营销自动化缺环分析

> 基于全模块代码审查，从"营销工作全流程自动化"视角出发，分析当前系统的缺环、优化方向，以及 Skills 系统的改进方案。

---

## 一、当前 Pipeline 的完成度

Conductor 定义了一条六阶段流水线，但各阶段完成度差异很大：

| 阶段 | 状态 | 说明 |
|------|------|------|
| Stage 1 感知 (Scan) | **已完成** | newsbot 采集 + JOA API 搜索，覆盖微博/抖音/小红书/B站/快手/知乎 |
| Stage 2 构思 (Ideate) | **已完成** | 快速模式（LLM 直出 5 个创意）+ 深度模式（调用脑暴五人团） |
| Stage 3 创作 (Create) | **已完成** | 多平台文案 + 视觉 Prompt + Seedream 图片生成 + AI 自评 |
| Stage 4 发布 (Publish) | **基本完成** | Playwright 自动发布小红书/微博，支持存仓库+人工审批模式 |
| Stage 5 互动 (Engage) | **仅骨架** | `check_and_reply()` 写了"功能开发中"，`generate_reply()` 可用但未接入采集 |
| Stage 6 复盘 (Review) | **仅骨架** | `generate_review()` 写了"功能开发中"，`ReviewReport` 模型已定义但没数据来源 |

**结论：从"发完就算"的角度看完成度不错；但从营销闭环看，发布之后的互动和复盘是断的——内容发出去了但不知道效果如何、不能自动回复评论、不能用数据反哺下一轮选题。**

---

## 二、营销全流程中缺失的环节

### 2.1 发布后的数据回收（最大缺环）

当前系统是**单向流水线**：感知→构思→创作→发布。但营销是个**飞轮**，需要：

```
感知 → 构思 → 创作 → 发布 → 数据回收 → 效果归因 → 选题优化
  ↑                                                    ↓
  └────────────────── 反馈闭环 ──────────────────────────┘
```

**缺什么：**
- 发布后没有采集阅读量/点赞/评论/转发数据
- 没有内容表现的历史数据库（什么选题火了、什么扑了）
- 下一次 `scan_trends` 和 `generate_ideas` 无法参考历史表现
- 没有 A/B 测试能力（同一选题不同角度，看哪个效果好）

### 2.2 评论互动闭环

`engager.py` 有 `generate_reply()` 但缺：
- 评论采集（JOA API 有搜索但没有"获取某帖子的评论"）
- 负面评论预警（比如出现品牌危机苗头时在飞书告警）
- 互动策略（先回复高赞评论、先回复提问型评论等优先级）

### 2.3 内容日历与排期

当前是"用户触发 → 立即生产 → 立即发布"模式，缺：
- 内容日历：这周要发什么、频率多少、各平台怎么分配
- 最佳发布时间：不同平台不同内容类型的最佳发布时间段
- 内容储备池：提前生产好放着，到时间自动发
- 节假日/热点日历：提前准备节日营销内容

### 2.4 受众画像与分层

当前的 `persona`（人设）和 `target_audience`（目标受众）是用户手动输入的一次性参数，缺：
- 粉丝画像数据（从各平台数据反推）
- 内容偏好学习（什么类型的内容粉丝更喜欢）
- 分层运营（针对不同粉丝群体生产不同内容）

### 2.5 竞品监控

`sentiment/` 做了舆情监控但主要是品牌维度，缺：
- 竞品内容追踪（竞品发了什么、效果如何）
- 竞品差异化分析（我们和竞品的内容策略差异在哪）
- 行业基准对比（我们的数据在行业中是什么水平）

### 2.6 跨机器人记忆

目前各机器人之间几乎没有共享记忆：
- 脑暴结果保存在 `runs/` 目录的 txt 文件里，但 conductor 只在同一次 pipeline run 中读取
- assistant 的 memo 和 planner 的规划结果不会反哺给 conductor
- sentiment 发现的舆情洞察不会自动影响下一次选题

---

## 三、Skills 系统的改进方案

### 3.1 当前状况

Skills 系统设计理念很好（插件化、自动发现、按需加载），但存在三个问题：

**问题 1：只有 2 个 Skill，且使用面窄**

| Skill | 谁在用 | 谁没用但应该用 |
|-------|--------|---------------|
| `brand` | brainstorm, conductor/idea_engine | creative（用自己的 knowledge.py 而不是 skills/brand）、engager、content_factory |
| `marketing` | planner | brainstorm（脑暴时也应该参考营销方法论）、conductor |

**问题 2：Skill 只提供"知识注入"，不提供"能力注入"**

当前 `Skill.get_context()` 只返回字符串（拼入 prompt 的文本），不能返回结构化数据或执行动作。这意味着 Skill 只能做"你应该知道这些"，不能做"你可以调用这个工具"。

**问题 3：机器人不知道有哪些 Skill 可用**

所有调用都是硬编码的 `load_context("brand")` / `load_context("marketing")`。机器人没有"我该加载什么 Skill"的自主决策能力。

### 3.2 建议的改进方案

#### 方案核心：从"知识注入"升级为"知识 + 能力 + 记忆"三层

```python
class Skill(ABC):
    name: str
    description: str

    # 第一层：知识（现有）
    def get_context(self, **kwargs) -> str: ...

    # 第二层：能力（新增）— 让机器人可以调用 Skill 的函数
    def get_tools(self) -> list[ToolDef]: ...

    # 第三层：记忆（新增）— 让 Skill 可以积累数据
    def remember(self, key: str, value: Any) -> None: ...
    def recall(self, key: str) -> Any: ...
```

#### 具体建议的新 Skills

**1. `skills/content_history.py` — 内容表现记忆**

```
作用：记录每次发布的效果数据，供 idea_engine 和 content_factory 参考
注入时机：构思阶段（generate_ideas 时提供"过去什么选题火了"的上下文）
数据来源：reviewer 阶段采集的数据、手动录入
```

这是打通反馈闭环的关键 Skill。idea_engine 调用 `load_context("content_history", topic="咖啡")` 就能得到"过去咖啡相关内容的表现数据：标题A 阅读2万点赞800，标题B 阅读5000点赞200"。

**2. `skills/audience.py` — 受众画像**

```
作用：提供目标受众的画像、偏好、活跃时间等
注入时机：构思 + 创作阶段
数据来源：YAML 配置 + 效果数据反推（哪类内容互动率最高）
```

替代当前手动传入的 `persona` / `target_audience` 参数。

**3. `skills/calendar.py` — 营销日历**

```
作用：提供节假日、行业活动、品牌关键日期
注入时机：感知阶段（scan_trends 时叠加日历事件）、构思阶段
数据来源：YAML 配置 + 公共 API
```

比如 3 月 8 日 scan_trends 时自动把"妇女节"注入热点，让 idea_engine 知道应该做节日营销内容。

**4. `skills/competitor.py` — 竞品知识**

```
作用：提供竞品的账号信息、内容策略、近期热门内容
注入时机：构思阶段（差异化时参考竞品）
数据来源：YAML 配置 + 定期采集
```

**5. `skills/platform_rules.py` — 平台规则**

```
作用：各平台的内容规范、字数限制、敏感词、推荐算法特点
注入时机：创作阶段（content_factory 生成文案时遵守平台规则）
数据来源：YAML 配置
```

当前 `COPYWRITING_SYSTEM` prompt 里硬编码了"小红书标题用 emoji"之类的规则，应该抽成 Skill，这样可以随时更新而不需要改代码。

**6. `skills/tone.py` — 账号调性/人设**

```
作用：定义各账号的发言人设、语气风格、禁忌用语
注入时机：创作阶段、互动阶段（回复评论时也要保持人设）
数据来源：YAML 配置
```

和 brand 不同，tone 是"我们的账号像什么人在说话"，brand 是"品牌长什么样"。

### 3.3 让机器人自动发现并加载 Skills

当前是硬编码调用 `load_context("brand")`，建议改为：

```python
# skills/__init__.py 新增
def auto_inject(task_type: str, **kwargs) -> str:
    """
    根据任务类型自动选择并加载相关 Skills。

    task_type: "ideation" / "creation" / "engagement" / "review"
    kwargs: topic, brand, platform 等上下文

    每个 Skill 声明自己适用的 task_types，auto_inject 自动匹配。
    """
    parts = []
    for skill in _registry.values():
        if task_type in skill.applicable_tasks:
            ctx = skill.get_context(**kwargs)
            if ctx:
                parts.append(ctx)
    return "\n\n".join(parts)
```

这样机器人只需要调用 `skills.auto_inject("ideation", topic="咖啡", brand="sky")`，Skills 系统就会自动把品牌知识、营销方法论、内容历史表现、受众画像、营销日历全部拼好返回。新加的 Skill 不需要改任何机器人代码就能自动生效。

---

## 四、具体优化建议（按投入产出比排序）

### 第一优先级：补上数据回收，打通闭环

| 任务 | 改动点 | 预估工作量 |
|------|--------|-----------|
| 1. 实现 `reviewer.py` | 通过 JOA API 或 Playwright 采集发布后的阅读/点赞/评论数据 | 中 |
| 2. 新建 `skills/content_history.py` | 存储和查询历史内容表现数据 | 小 |
| 3. `idea_engine.py` 接入 content_history | 选题时参考历史数据："类似话题上次阅读 2 万" | 小 |

**为什么最优先：** 没有数据反馈，所有优化都是盲人摸象。有了数据才能迭代。

### 第二优先级：让 Skill 被更多机器人使用

| 任务 | 改动点 | 预估工作量 |
|------|--------|-----------|
| 4. `creative/bot.py` 改用 `skills/brand.py` | 删除 knowledge.py 中重复的品牌逻辑，统一数据源 | 小 |
| 5. `content_factory.py` 注入 brand Skill | 生成文案时也参考品牌调性 | 小 |
| 6. `engager.py` 注入 brand + tone Skill | 回复评论时保持品牌一致性 | 小 |
| 7. `brainstorm/run.py` 注入 marketing Skill | 脑暴时也参考营销方法论 | 小 |
| 8. 实现 `skills.auto_inject()` | 一个函数自动选择并拼装所有相关 Skill | 中 |

**为什么排第二：** 投入最小，立即生效。大部分是把已有功能接到更多地方。

### 第三优先级：补齐互动和排期

| 任务 | 改动点 | 预估工作量 |
|------|--------|-----------|
| 9. 实现 `engager.py` 评论采集 | 通过 JOA 或 Playwright 采集评论，结合 LLM 生成回复 | 中 |
| 10. 新建 `skills/calendar.py` | 营销日历，节假日/品牌活动/行业大事 | 小 |
| 11. 新建内容排期模块 | 支持"本周小红书发 3 条、抖音发 2 条"的排期计划 | 中 |
| 12. Cron 定时自动执行 | 每天定时 scan → ideate → create，储备内容池 | 小（cron_server 已有） |

### 第四优先级：高级能力

| 任务 | 改动点 | 预估工作量 |
|------|--------|-----------|
| 13. 跨机器人记忆 | 共享的 KV 存储，让 sentiment 洞察自动影响 conductor 选题 | 中 |
| 14. 内容 A/B 测试 | 同一选题生成多个版本，分别发布，比较效果 | 大 |
| 15. 竞品追踪 | 定期采集竞品内容和数据，生成竞品分析报告 | 大 |
| 16. 视频脚本生成 | 当前只有图文，缺少短视频脚本（分镜、字幕、BGM 建议） | 中 |

---

## 五、Skills 落地的具体操作路径

如果你想让机器人使用你希望它们知道的知识，最快的路径是：

### Step 1：把知识写成 YAML 文件

在 `skills/data/` 下放 YAML（类似 `creative/brands/*.yaml` 的模式）：

```
skills/
  data/
    platforms/
      xiaohongshu.yaml    # 小红书的内容规范、算法特点、最佳实践
      douyin.yaml          # 抖音的规则
    audiences/
      gen_z_female.yaml    # 受众画像
    calendar/
      2026_marketing.yaml  # 2026 年营销日历
    competitors/
      competitor_a.yaml    # 竞品信息
```

### Step 2：为每类知识写一个 Skill

仿照 `skills/brand.py` 的模式，每个 Skill 做三件事：
1. 从 YAML 加载数据
2. 格式化成 LLM 能理解的文本
3. 注册到全局注册表

### Step 3：在 Skill 基类上加 `applicable_tasks`

```python
class PlatformRulesSkill(Skill):
    name = "platform_rules"
    applicable_tasks = ["creation", "engagement"]  # 创作和互动时自动注入

    def get_context(self, platform="xiaohongshu", **kwargs) -> str:
        # 加载对应平台的 YAML，返回格式化文本
        ...
```

### Step 4：在 Pipeline 关键节点调用 `auto_inject`

只需要在 `idea_engine.py`、`content_factory.py`、`engager.py` 各加一行：

```python
from skills import auto_inject
extra_context = auto_inject("creation", topic=topic, brand=brand, platform=platform)
```

**效果：以后你加任何新知识，只要放 YAML + 写一个 Skill 文件，所有机器人就自动获得这个知识，不需要改任何机器人代码。**

---

## 六、总结

当前系统的核心能力（感知→构思→创作→发布）已经跑通，最大的缺环是**数据回收和反馈闭环**——发布之后不知道效果，无法用数据驱动下一轮选题。其次是 **Skills 利用率低**——设计了很好的插件架构，但只有 2 个 Skill 且只有少数机器人在用。

推荐路径：先补 reviewer（数据回收）→ 再扩展 Skills（让所有机器人都变聪明）→ 再补互动和排期（完整闭环）→ 最后做竞品和 A/B 测试（高级优化）。
