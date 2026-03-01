# skills/ — 共享技能库

所有机器人都可以调用的领域知识库。

## 已有技能

| 技能 | 说明 | 数据来源 |
|------|------|----------|
| `brand` | 品牌知识（视觉风格、原则、场景、文案调性） | `creative/brands/*.yaml` |
| `marketing` | 营销方法论（策略框架、行业 SOP） | `CN-MKT-Skills/modules/*.md` |

## 快速使用

```python
from skills import load_context, list_skills

# 查看所有可用技能
for s in list_skills():
    print(f"{s.name}: {s.description}")

# 加载品牌知识（按名称）
ctx = load_context("brand", brand_name="sky")

# 加载品牌知识（从文本自动识别）
ctx = load_context("brand", detect_from="帮我做一个春日系列的素材")

# 加载营销知识（全部摘要）
ctx = load_context("marketing")

# 加载营销知识（按关键词筛选）
ctx = load_context("marketing", keywords=["社交媒体", "用户获取"])
```

## 添加新技能

1. 在 `skills/` 下创建 `.py` 文件
2. 继承 `Skill` 基类，实现 `get_context()` 方法
3. 在文件末尾调用 `register(YourSkill())`

```python
from skills import Skill, register

class MySkill(Skill):
    name = "my_skill"
    description = "这个技能做什么"

    def get_context(self, **kwargs) -> str:
        # 返回可以拼入 LLM prompt 的文本
        return "..."

register(MySkill())
```

新文件会在 `import skills` 时自动被发现和注册。

## 哪些机器人在用

- **brainstorm**：自动检测话题中的品牌，注入品牌知识到讨论上下文
- **planner**：加载营销知识库摘要作为规划参考
- **creative**：使用自己的品牌加载逻辑（`creative/knowledge.py`），数据来源与 brand skill 相同
