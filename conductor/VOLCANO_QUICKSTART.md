# 火山生成内容 — 操作说明

Pipeline 在 **CREATE（创作）** 阶段会自动调用火山方舟 Ark：先由 creative 模块生成视觉 Prompt，再用 **Seedream 文生图** 得到图片并写入草稿。

---

## 一、前置配置

在项目根目录 `.env` 中至少配置其一（和豆包 LLM 同平台，可复用）：

```bash
# 方式 1：已有豆包 Key 可直接复用
DOUBAO_API_KEY=你的_key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

# 方式 2：单独配置火山方舟 Key（可选）
# ARK_API_KEY=你的_key
```

获取 API Key：  
https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey  

依赖已包含在项目里：`volcengine-python-sdk[ark]`。

---

## 二、怎么「走」火山生成这一步

### 方式 A：飞书触发（推荐）

1. 启动自媒体助手：`python3 -m conductor`
2. 在飞书里打开和「自媒体助手」的对话
3. 发一条**主题**，例如：  
   `帮你打工bot 今天完成的一条小红书内容`  
   或走深度：  
   `深度：第一条帮你打工日常`
4. 等待流程跑完：**扫描 → 创意（或脑暴→创意）→ 创作**。  
   在 **创作** 阶段会：
   - 生成文案 + 视觉 Prompt（含 Seedance 英文）
   - **自动调火山 Seedream 文生图**，把图片 URL 写入草稿
5. 在飞书里会收到结果卡片；用「**详情 &lt;id&gt;**」可看文案 + Prompt + 已生成素材。

只要 `.env` 里 `DOUBAO_API_KEY`（或 `ARK_API_KEY`）正确，无需额外开关，创作阶段就会尝试调用火山生成图片。

---

### 方式 B：命令行跑整条 Pipeline

不通过飞书，直接跑一遍「扫热点 → 创意 → 创作（含火山）」：

```bash
cd /Users/celeste/AIlarkteams
python3 -m conductor.cli --topic "帮你打工bot 第一条内容" --platforms "小红书"
```

深度模式（先脑暴再 creative prompt 再创作）：

```bash
python3 -m conductor.cli --topic "第一条帮你打工日常" --deep --platforms "小红书"
```

跑完后终端会打印：创意、文案、视觉 Prompt、以及是否成功调用火山生成图片（如「即梦图片生成完成: 1 张」）。

---

### 方式 C：单独测火山接口（排查用）

只验证「火山能不能出图/出视频」、不跑完整 pipeline：

```bash
cd /Users/celeste/AIlarkteams
PYTHONPATH=. python3 conductor/test_volcano.py          # 默认只测文生图
PYTHONPATH=. python3 conductor/test_volcano.py --video  # 只测文生视频 (Seedance 1.5，约 1～3 分钟)
PYTHONPATH=. python3 conductor/test_volcano.py --all   # 先图后视频都测
```

- 文生图：默认 **Seedream 4.5**，尺寸需至少 1920x1920。
- 文生视频：默认 **Seedance 1.5**（`doubao-seedance-1-5-pro-251215`），提交任务后轮询直至完成。

**查看生成的图/视频**：脚本会打印 URL，复制到浏览器即可打开。加 `--download` 可下载到 `data/conductor/assets/`。跑完整 Pipeline 后可在飞书发「详情 &lt;id&gt;」看该条内容的素材链接。

若报错 `未配置火山方舟 API Key`，检查 `.env` 里的 `DOUBAO_API_KEY` 或 `ARK_API_KEY`。  
若报 Ark 接口错误，需在火山控制台确认该 Key 已开通「图像生成」类能力。

---

## 三、当前流程里「火山」在做什么

| 步骤       | 说明 |
|------------|------|
| 文案 + 视觉 Prompt | 由 **creative** 模块（同 creative prompt 机器人逻辑）根据选题生成中文视觉描述 + Seedance 英文 Prompt。 |
| 火山生成图片 | **content_factory** 用上面的英文 Prompt（或中文前 200 字）调用 `conductor.visual.generate_image`，即 **Seedream 4.5** 文生图，得到图片 URL，写入 `draft.generated_assets`。 |
| 视频       | 默认视频模型为 **Seedance 1.5**（`doubao-seedance-1-5-pro-251215`）。当前 pipeline 仅自动调文生图；文生视频可通过 `conductor.visual.generate_video` 单独测，或在 `content_factory` 里对 `short_video` 增加调用。 |

---

## 四、常见问题

- **没有生成图片**：看终端或日志里是否出现「跳过图片生成」或「图片生成失败」。通常是未配置 Key 或 Key 无图像权限；用上面的「方式 C」单独测一次即可定位。
- **只想要 Prompt、不想调火山**：目前创作阶段会自动尝试调火山；若希望完全跳过，需要在 `conductor/stages/content_factory.py` 里注释掉「尝试调用即梦 AI 生成实际图片」那一整块逻辑。
- **想生成视频**：`conductor.visual` 已提供 `generate_video()`，但 pipeline 默认只调了 `generate_image()`；如需视频，要在创作阶段根据 `content_type` 或配置增加对 `generate_video` 的调用。
