# skills/ — 共享技能库

所有机器人都可以调用的领域知识库。通过 `core/skill_router.py` 自动路由，bot 只需一行代码即可接入全部技能。

## 架构

```
用户消息 → skill_router.enrich_prompt()
                ↓
         遍历所有已注册 Skill
                ↓
         should_activate() 判断是否激活
                ↓
         get_context() 提取知识
                ↓
         追加到 system prompt → 发给 LLM
```

## 已有技能

| 技能 | 说明 | 数据来源 | 自动激活条件 |
|------|------|----------|-------------|
| `brand` | 品牌知识（视觉风格、原则、场景、文案调性） | `creative/brands/*.yaml` | creative / conductor bot，或消息含"品牌""调性"等关键词 |
| `marketing` | 营销方法论（策略框架、行业 SOP） | `CN-MKT-Skills/modules/*.md` | planner / conductor bot，或消息含"营销""推广"等关键词 |

## 快速使用

### 方式一：自动路由（推荐）

Bot 里调 `enrich_prompt()` 一行搞定，router 自动判断要加载哪些技能：

```python
from core.skill_router import enrich_prompt

system = enrich_prompt(
    "你是内容助手...",        # 原始 system prompt
    user_text=user_message,   # 用户消息（用于激活判断）
    bot_type="creative",      # 当前 bot 类型
)
# system 现在可能包含自动注入的品牌/营销知识
```

### 方式二：手动指定技能

```python
system = enrich_prompt(
    "你是内容助手...",
    skill_names=["brand", "marketing"],  # 手动指定
    brand_name="my_brand",               # 透传给 skill
)
```

### 方式三：直接调用

```python
from skills import load_context, list_skills

ctx = load_context("brand", brand_name="sky")
ctx = load_context("brand", detect_from="帮我做一个春日系列的素材")
ctx = load_context("marketing", keywords=["社交媒体"])
```

## CLI 工具

```bash
python -m skills list                     # 列出所有已注册技能
python -m skills test brand               # 测试品牌技能
python -m skills test brand brand_name=sky # 带参数测试
python -m skills activate "帮我做品牌推广"  # 查看哪些技能会被激活
```

## 添加新技能

1. 在 `skills/` 下创建 `.py` 文件
2. 继承 `Skill` 基类，实现 `get_context()` 和配置 `trigger_keywords`
3. 在文件末尾调用 `register(YourSkill())`

```python
from skills import Skill, register

class MySkill(Skill):
    name = "my_skill"
    description = "这个技能做什么"
    trigger_keywords = ["关键词1", "关键词2"]
    bot_types = ["creative", "planner"]  # 这些 bot 始终激活

    def get_context(self, **kwargs) -> str:
        return "可以拼入 LLM prompt 的领域知识文本..."

    def should_activate(self, user_text: str, bot_type: str = "", **kwargs) -> bool:
        # 可选：覆写默认激活逻辑
        return super().should_activate(user_text, bot_type)

register(MySkill())
```

新文件会在 `import skills` 时自动被发现和注册，无需修改任何配置。

## 各 Bot 接入情况

| Bot | 接入方式 | 说明 |
|-----|---------|------|
| **assistant** | `enrich_prompt()` | 日程助手，按需激活品牌/营销知识 |
| **brainstorm** | `enrich_prompt()` + 手动 `load_context("brand")` | 讨论中注入品牌知识 |
| **planner** | `enrich_prompt()` + 手动 `load_context("marketing")` | 规划时加载营销方法论 |
| **creative** | `build_system_prompt()` 内置 `enrich_prompt()` | 自动注入品牌 + 其他知识 |
| **conductor** | 各 stage 调用 `enrich_prompt()` | content_factory / idea_engine / engager |
| **newsbot** | 未接入 | 新闻分析不需要领域知识 |
| **sentiment** | 未接入 | 舆情分析不需要领域知识 |
