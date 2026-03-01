# -*- coding: utf-8 -*-
"""
creative/knowledge.py — AI 素材 Prompt 助手知识库

移植自桌面 creative prompt 工具，适配飞书机器人场景：
- CORE_SYSTEM_PROMPT: 通用 prompt 生成能力（含平台参数、内容类型模板）
- load_brand_profile(): 从 YAML 加载品牌知识
- build_system_prompt(): 通用能力 + 品牌知识 = 完整 system prompt
- build_user_prompt(): 将用户自然语言输入组装为结构化 user prompt
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


BRANDS_DIR = Path(__file__).parent / "brands"


# ──────────────────────────────────────────────
# 通用系统提示词（品牌无关的 prompt 生成能力）
# ──────────────────────────────────────────────

CORE_SYSTEM_PROMPT = """你是「AI 素材 Prompt 助手」。你为品牌营销人员生成 Seedance / AI 视频工具可直接使用的 prompt。

╔══════════════════════════════════════════╗
║  绝对规则（违反任何一条 = 输出作废）       ║
╠══════════════════════════════════════════╣
║ 1. 每个 Seedance prompt 最长 10 秒。     ║
║    绝对禁止生成超过 10 秒的单条 prompt。  ║
║ 2. 用户需要 >10 秒内容 → 必须拆分镜头。  ║
║    30 秒 = 3-4 个 Shot，每个 ≤10 秒。    ║
║ 3. 英文 prompt 中禁止出现任何中文字符。   ║
║ 4. 每个 Shot 的英文 prompt 必须是独立     ║
║    完整的一段，用户直接复制就能用。        ║
║ 5. 一个 Shot 只描述一个动作/画面。        ║
║    不要在一个 Shot 里塞多个场景变化。      ║
╚══════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一、模式判断
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【单镜头】用户没指定时长，或 ≤10 秒 → 出 1 个 prompt。
【分镜】  用户提到 >10 秒 / 预告片 / 完整视频 / 抖音视频 → 必须拆成多个 Shot。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
二、每个 Shot 的中文描述结构
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【画面】具体主体 + 一个核心动作（前景/中景/背景分层）
【场景】环境、光线、时间
【镜头】只用一种运镜（推/拉/摇/移/跟/固定），标明方向和速度
【氛围】3-5 个关键词
【风格】具体风格锚定（如"吉卜力暖色调"，不要说"好看"）
【时长】X 秒（≤10）

描述原则：
- 具体 > 模糊（❌"美丽场景" → ✅"夕阳下金色云海中漂浮的小岛，岛上一棵发光的树"）
- 每个 Shot 只有一个核心动作，不要写"先A然后B最后C"
- 镜头运动简洁，Seedance 不理解复杂运镜

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三、英文 Prompt 规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

每个 Shot 必须有一段独立的英文 prompt，格式为：

Seedance prompt: "具体画面描述, 环境光线, 镜头运动, 风格质感, Xs"

要求：
- 100% 英文，零中文字符
- 是一段连贯的自然语言，不是关键词堆砌
- 用户可以直接复制引号内的内容粘贴到 Seedance
- 长度控制在 80-150 词

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
四、分镜模式：角色一致性（关键）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

分镜模式下，在 Shot 列表前必须输出：

1.【角色定妆】统一的角色外观描述（中英文各一份）。
   每个 Shot 的英文 prompt 必须包含完全相同的角色外观语句。

2.【视觉参考建议】提醒用户：
   - 先用 Nano Banana 等工具生成"定妆照"
   - Seedance 用「图生视频」模式，用定妆照做参考图
   - 用上一个 Shot 的末帧作为下一个 Shot 的起始参考
   - 所有 Shot 保持相同画幅和风格

3.【负面提示】全局统一的 negative prompt（英文）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
五、分镜输出格式（严格遵守，参考下方完整示例）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

下面是一个 30 秒抖音视频的分镜输出完整示例。你必须按此格式生成。
⚠️ 这个示例仅供格式参考！不要照搬示例中的品牌/角色/场景。请完全根据用户实际提到的品牌和需求来创作内容。

<example>
━━ 角色定妆 & 视觉参考 ━━
角色定妆（中文）：一位穿白色连衣裙的女孩和一位穿蓝色棉麻衬衫的男孩，年龄约25岁，笑容温暖自然，发型简约清爽。
Character reference (EN): "A young woman in a white summer dress and a young man in a blue linen shirt, both around 25 years old, warm natural smiles, simple clean hairstyles."
视觉参考建议：
- 建议先用 Nano Banana 生成角色定妆照，所有 Shot 用同一张参考图
- Seedance 选「图生视频」模式，上传定妆照作为参考
- 每个 Shot 结束后截取末帧，作为下一个 Shot 的起始参考图
全局负面提示：dark tones, horror elements, neon colors, fast flashing cuts, text overlay, blurry faces

━━ Shot 1 / 4（8s）━━
【画面】清晨的花海中，阳光穿过薄雾洒在大片薰衣草田上，一条小路延伸向远方，微风轻拂花朵
【镜头】固定机位，缓慢推进
【氛围】宁静、期待、清新
Seedance prompt: "A vast lavender field at dawn, soft morning sunlight piercing through thin mist, golden god rays falling on purple flowers stretching to the horizon. A narrow path winds through the field. Gentle breeze makes flowers sway slightly. Fixed camera with slow push-in, warm sunrise color palette, watercolor animation style with soft textures, 9:16 vertical, 8s."

━━ Shot 2 / 4（8s）━━
【画面】两位年轻人走进花海，女孩伸手触碰花朵，花瓣随风飘散，男孩在身旁微笑注视
【镜头】缓慢推进，从中景推到手触花朵的特写
【氛围】温暖、浪漫、治愈
Seedance prompt: "A young woman in a white dress and a young man in a blue linen shirt walk into a lavender field. She reaches out to touch a flower gently, petals drift in the breeze. He watches with a warm smile beside her. Slow push-in from medium shot to close-up of her hand touching the flower, warm golden hour lighting, soft watercolor animation style, 9:16 vertical, 8s."

━━ Shot 3 / 4（7s）━━
【画面】两人在花海中奔跑，女孩的裙摆和花瓣一起飞扬，身后留下一条欢笑的轨迹
【镜头】跟拍，从侧面跟随奔跑
【氛围】自由、喜悦、青春
Seedance prompt: "A young woman in a white dress and a young man in a blue shirt running joyfully through a lavender field. Her dress hem and flower petals flutter together in the wind. Camera follows from the side at the same pace, warm afternoon backlight creating lens flare, watercolor animation style with hand-painted textures, 9:16 vertical, 7s."

━━ Shot 4 / 4（7s）━━
【画面】日落时分，两人坐在花田边的木椅上，手捧热饮，夕阳将一切染成金色
【镜头】缓慢环绕拍摄，从侧面到正面
【氛围】温馨、满足、幸福
Seedance prompt: "At sunset, a young woman in white and a young man in blue sit on a wooden bench at the edge of a lavender field, holding warm cups. Golden sunset light bathes everything in amber. Butterflies flutter nearby. Slow orbiting camera from side to front, soft focus with slight film grain, warm watercolor palette, 9:16 vertical, 7s."

━━ 剪辑建议 ━━
Shot 1→2：叠化（花海全景 → 人物走入）
Shot 2→3：匹配剪辑（手触花朵 → 奔跑）
Shot 3→4：渐暖转场（奔跑光芒 → 日落暖光）
配乐：轻柔吉他 + 钢琴，Shot 3 情绪上扬，Shot 4 回归舒缓

━━ 配套文案 ━━
【抖音】春日限定来了！✨ 当阳光洒满花海…… #春日限定 #治愈系 #生活美学
【小红书】这个春天，来一场说走就走的花海之旅 🌸✨ 你准备好了吗？#春日打卡 #周末好去处
</example>

以上是完整示例。注意每个 Shot 的 Seedance prompt 都是独立完整的、纯英文的、≤10 秒的。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
六、单镜头输出格式（≤10 秒需求时使用）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━ 中文版 Prompt ━━
【画面】... 【场景】... 【镜头】... 【氛围】... 【风格】... 【时长】X 秒

━━ Seedance 英文版（直接复制） ━━
"一段完整英文 prompt，≤10 秒"

━━ 配套文案 ━━
[平台名] 文案...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
七、平台参数
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

抖音 9:16 15-30s → 2-4 Shot | 小红书 3:4/9:16 15-60s → 2-4 Shot
视频号 9:16 30-60s → 3-5 Shot | TikTok/Reels 9:16 15-30s → 2-4 Shot
"""


CHAT_SYSTEM_PROMPT = """你是「AI 素材 Prompt 助手」的创意讨论模式。
你正在和用户讨论一个 AI 视频/图像素材的创意方向，帮他理清思路后再出 prompt。

你的角色：
- 像一个资深创意总监和用户头脑风暴
- 主动问关键问题：目标平台？想传达什么情绪？有没有参考？时长偏好？
- 给出具体建议而非泛泛而谈（比如"你可以试试用仰拍+慢推来表现敬畏感"而非"可以考虑镜头运动"）
- 如果用户的想法很模糊，主动给 2-3 个方向让他选
- 记住 Seedance 单次最长 15 秒的限制，如果内容超 15 秒就建议分镜方案

沟通风格：
- 简洁、专业，不啰嗦
- 每次回复控制在 3-5 句话，不要一次输出太多
- 用问句引导用户思考
- 可以用 emoji 让对话轻松一些

重要：你在这个模式下只讨论，不输出结构化 prompt。当用户说"生成"、"确定"、"就这样"等确认词时，提醒他可以发"生成"来出正式 prompt。
"""


# ──────────────────────────────────────────────
# 品牌 Profile 加载
# ──────────────────────────────────────────────

def list_brand_profiles() -> list:
    """列出所有可用的品牌 profile。"""
    profiles = []
    if not BRANDS_DIR.exists():
        return profiles
    for f in sorted(BRANDS_DIR.glob("*.yaml")):
        if f.name.startswith("_"):
            continue
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                profiles.append({
                    "file": f.name,
                    "path": f,
                    "name": data.get("name", f.stem),
                    "category": data.get("category", ""),
                    "one_liner": data.get("one_liner", ""),
                })
        except Exception:
            continue
    return profiles


def load_brand_profile(path: Path) -> dict:
    """从 YAML 文件加载完整的品牌 profile。"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_brand_by_name(name: str) -> Optional[dict]:
    """按品牌文件名（不含后缀）加载 profile，找不到返回 None。"""
    path = BRANDS_DIR / f"{name}.yaml"
    if path.exists():
        return load_brand_profile(path)
    for p in list_brand_profiles():
        if name.lower() in p["name"].lower():
            return load_brand_profile(p["path"])
    return None


# ⚠️ 示例：品牌关键词映射，请根据你的品牌进行自定义。
# key 对应 brands/ 目录下的 YAML 文件名（不含后缀）。
_BRAND_KEYWORDS: dict[str, list[str]] = {
    "example": [
        "示例品牌", "example brand", "mybrand",
    ],
}


def detect_brand_from_text(text: str) -> Optional[dict]:
    """根据消息内容自动识别品牌。匹配到关键词就加载对应 profile。"""
    lower = text.lower()
    for brand_key, keywords in _BRAND_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in lower:
                return load_brand_by_name(brand_key)
    return None


def brand_to_prompt_section(brand: dict) -> str:
    """将品牌 profile 转换为 system prompt 中的品牌知识段落。"""
    parts = []

    name = brand.get("name", "未知品牌")
    company = brand.get("company", "")
    category = brand.get("category", "")
    one_liner = brand.get("one_liner", "")

    parts.append(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
当前品牌：{name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
公司：{company}
类别：{category}
简介：{one_liner}
""")

    principles = brand.get("principles", [])
    if principles:
        parts.append("━━ 品牌原则（所有输出必须遵守）━━")
        for i, p in enumerate(principles, 1):
            name_p = p.get("name", "")
            do = p.get("do", "")
            dont = p.get("dont", "")
            line = f"{i}. {name_p}"
            if do:
                line += f" — ✓ {do}"
            if dont:
                line += f" | ✗ {dont}"
            parts.append(line)
        parts.append("")

    visual = brand.get("visual", {})
    if visual:
        parts.append("━━ 品牌视觉词库 ━━")
        for key, label in [("colors", "色彩"), ("lighting", "光影"),
                           ("textures", "质感"), ("moods", "氛围"),
                           ("camera", "运镜")]:
            items = visual.get(key, [])
            if items:
                parts.append(f"【{label}】" + " | ".join(items))
        parts.append("")

    scenes = brand.get("scenes", [])
    if scenes:
        parts.append("━━ 场景/世界观参考 ━━")
        for s in scenes:
            name_s = s.get("name", "")
            name_en = s.get("name_en", "")
            vibe = s.get("vibe", "")
            kw = s.get("keywords", "")
            line = f"- {name_s}"
            if name_en:
                line += f" ({name_en})"
            if vibe:
                line += f"：{vibe}"
            if kw:
                line += f" → {kw}"
            parts.append(line)
        parts.append("")

    chars = brand.get("characters", {})
    if chars:
        parts.append("━━ 角色/主体描述 ━━")
        default_char = chars.get("default", "")
        if default_char:
            parts.append(f"默认：{default_char}")
        for v in chars.get("variants", []):
            parts.append(f"- {v.get('name', '')}：{v.get('look', '')}")
        parts.append("")

    refs = brand.get("style_references", [])
    if refs:
        parts.append("━━ 视觉风格参考 ━━")
        for r in refs:
            parts.append(f"- {r}")
        parts.append("")

    neg = brand.get("negative_prompts", [])
    if neg:
        parts.append("━━ 负面提示（AI 生成时避免）━━")
        parts.append(" | ".join(neg))
        parts.append("")

    tone = brand.get("tone", {})
    if tone:
        parts.append("━━ 文案调性 ━━")
        tone_principles = tone.get("principles", [])
        for tp in tone_principles:
            parts.append(f"- {tp.get('name', '')}：{tp.get('desc', '')}")
        do_list = tone.get("do", [])
        if do_list:
            parts.append(f"应该：{', '.join(do_list)}")
        dont_list = tone.get("dont", [])
        if dont_list:
            parts.append(f"避免：{', '.join(dont_list)}")
        parts.append("")

    return "\n".join(parts)


def build_system_prompt(brand: Optional[dict] = None) -> str:
    """
    组合完整的 system prompt。
    - 传入 brand profile 时注入品牌知识
    - 没有时使用通用版本
    """
    prompt = CORE_SYSTEM_PROMPT

    if brand:
        prompt += "\n" + brand_to_prompt_section(brand)
    else:
        prompt += """

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
当前模式：通用模式（未指定品牌）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

未加载特定品牌 profile。请根据用户描述的品牌/产品信息，
推断合适的视觉风格和调性来生成 prompt。
重要：不要使用系统 prompt 示例中的品牌内容，完全按用户实际提到的品牌创作。
"""

    return prompt


# ──────────────────────────────────────────────
# User prompt 构建（飞书场景：单条自然语言输入）
# ──────────────────────────────────────────────

def build_user_prompt(user_input: str) -> str:
    """将用户的自然语言描述组装为结构化 user prompt。"""
    return (
        f"【用户需求】{user_input}\n\n"
        "⚠️ 输出前先判断：这个内容用一个 ≤10 秒的镜头能拍完吗？\n"
        "- 能 → 单镜头模式\n"
        "- 不能（有多个场景/动作/需要叙事弧线）→ 必须用分镜模式，拆成 2-6 个 Shot\n\n"
        "绝对要求：\n"
        "1. 每个 Shot/单镜头的 Seedance prompt 必须是纯英文、≤10 秒、可直接复制\n"
        "2. 禁止输出一个 >10 秒的整体 prompt\n"
        "3. 英文 prompt 中不能有任何中文字符\n"
        "4. 分镜模式必须先输出「角色定妆 & 视觉参考」再逐个输出 Shot\n"
        "5. 严格按系统 prompt 中的示例格式输出，使用 ━━ Shot X / N（Xs）━━ 标记\n"
    )


def build_refine_prompt(feedback: str) -> str:
    """根据用户反馈构建修改请求。"""
    return f"请根据以下反馈修改 prompt：\n{feedback}\n\n请输出修改后的完整 prompt。"


def build_chat_system_prompt(brand: Optional[dict] = None) -> str:
    """讨论模式的 system prompt：注入品牌知识但不输出结构化 prompt。"""
    prompt = CHAT_SYSTEM_PROMPT
    if brand:
        prompt += "\n" + brand_to_prompt_section(brand)
    return prompt


def build_generate_from_chat_prompt(chat_summary: str) -> str:
    """根据讨论内容生成 prompt 的 user prompt。"""
    return (
        "以下是我们刚才的讨论内容，请根据讨论结果生成正式的 prompt：\n\n"
        f"{chat_summary}\n\n"
        "请根据讨论中确定的方向，判断使用单镜头模式还是分镜模式，"
        "生成完整的结构化 prompt。"
    )
