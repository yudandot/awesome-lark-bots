# 一条龙测试：飞书发需求 → 自动发一篇小红书

从在飞书给自媒体助手发一条消息开始，到小红书后台自动出现一篇笔记，完整跑通需要下面条件和步骤。

---

## 能力是否具备

| 环节 | 能力 | 说明 |
|------|------|------|
| 飞书收消息 | ✅ | 长连接已接通，发「帮助」可验证 |
| 主题 → 创意 | ✅ | 快速模式用 LLM，深度模式用脑暴→creative prompt 生成火山需求 |
| 创意 → 文案+素材 | ✅ | content_factory 生成多平台文案；可选 Ark 文生图 |
| 存草稿 | ✅ | Create 阶段会写入 `data/conductor/content/` |
| 自动发小红书 | ✅ | Playwright + 持久化浏览器（~/.conductor-chrome），需先登录一次 |

结论：**具备一条龙能力**。需在本机满足「前置条件」并开启「自动发布」后，在飞书发主题即可跑满流程并自动发一篇小红书。

---

## 前置条件（跑通前请逐项确认）

1. **飞书机器人**
   - 已配置 `CONDUCTOR_FEISHU_APP_ID` / `CONDUCTOR_FEISHU_APP_SECRET`，且 `python3 -m conductor` 能连上飞书。

2. **小红书已登录（必做一次）**
   - 运行：`python3 conductor/login_helper.py --wait 180`
   - 在弹窗里登录小红书创作者中心，登录成功后关掉或等脚本结束。
   - Cookie 会保存在 `~/.conductor-chrome`，之后自动发布会用这份登录态。

3. **Playwright + Chrome**
   - 已安装：`pip install playwright`，且使用系统 Chrome（`channel="chrome"`），无需再 `playwright install chromium`。
   - 若从未跑过，可先：`python3 -m conductor.test_browser` 验证浏览器能打开。

4. **开启自动发布**
   - 在 `.env` 里加上或改为：
     ```bash
     CONDUCTOR_AUTO_PUBLISH=true
     ```
   - 这样飞书里发主题后，Pipeline 会跑完 Publish 阶段，并调用浏览器自动发小红书。

5. **可选：图片素材**
   - 若希望带图发小红书，需配置 `ARK_API_KEY` 或 `DOUBAO_API_KEY`，Ark 文生图可用；不配则发纯文字笔记也可跑通。

---

## 测试步骤

### 1. 启动自媒体助手

```bash
cd /path/to/AIlarkteams
python3 -m conductor
```

看到「正在连接飞书…」且无报错即可。

### 2. 在飞书发一条主题

和自媒体助手的对话里发一句，例如：

- **春天穿搭分享**
- **测试一条龙 并发布**

无需带「并发布」；只要 `CONDUCTOR_AUTO_PUBLISH=true`，本次 run 就会在完成后自动发小红书。

### 3. 等待 Pipeline 跑完

- 快速模式约 1～3 分钟：扫热点 → 产创意 → 生成内容 → 存草稿 → **自动发布**。
- 若开启深度模式（发「深度：新品发布会」），会先脑暴，再由 creative prompt 生成给火山的需求，时间更长。

过程中飞书会收到阶段进度；结束时会有结果卡片（含内容 ID、标题等）。

### 4. 自动发小红书时

- 会弹出 Chrome 窗口（或无头模式不弹窗），用 `~/.conductor-chrome` 的登录态打开小红书创作者中心并发布。
- 若未登录或登录过期，会报错，需重新跑一次 `login_helper.py` 登录。

### 5. 验证

- 打开 [小红书创作者中心](https://creator.xiaohongshu.com) → 笔记管理，看是否多了一篇刚生成的笔记。
- 或在飞书结果卡片里看是否有「已发布」/链接（若代码有把 post_url 写回卡片）。

---

## 哪里可以看生成的图和视频

| 场景 | 查看方式 |
|------|----------|
| **单独测火山**（`test_volcano.py`） | 脚本会打印「在浏览器中打开: https://...」；复制链接到浏览器即可。加 `--download` 会下载到 `data/conductor/assets/`。 |
| **跑完 Pipeline 后** | 飞书里发「**详情** &lt;内容 id&gt;」→ 卡片里会显示「已生成素材」及链接，点链接即可看图/视频。 |
| **本地文件** | 内容会存到 `data/conductor/content/&lt;id&gt;.json`，其中 `generated_assets` 为图片/视频 URL 列表；若发布时下载过素材，会在 `data/conductor/assets/`。 |
| **CLI** | `python3 -m conductor.cli --detail &lt;id&gt;` 会打印文案和视觉 Prompt；若该条有 `generated_assets`，需打开对应 URL 查看。 |

---

## 测自动发送（清单）

1. **安装 Playwright**（未装过的话）：`pip install playwright`（使用系统 Chrome，无需 `playwright install chromium`）。
2. **小红书先登录一次**：`python3 conductor/login_helper.py --wait 180`，在弹窗里登录创作者中心后关闭或等结束。
3. **开启自动发布**：在 `.env` 里设置 `CONDUCTOR_AUTO_PUBLISH=true`。
4. **启动自媒体助手**：`python3 -m conductor`。
5. **飞书发一条主题**：例如「测试自动发 帮你打工日常」。
6. **等 Pipeline 跑完**：创作阶段会生成文案+图；Publish 阶段会自动打开浏览器发小红书。
7. **验证**：小红书创作者中心 → 笔记管理里应有一篇新笔记。

若不想自动发、只想测到「发之前」：不设或设 `CONDUCTOR_AUTO_PUBLISH=false`，发主题后仍会生成并存草稿；在飞书里用「**自动发布** &lt;id&gt; 小红书」可手动触发一次发布。

---

## 生成素材有大小，能自动完成上传发布吗？

可以。流程是：

1. **生成阶段**：火山返回的是图片/视频的 URL，写入草稿的 `generated_assets`。
2. **发布阶段**：在真正发小红书时，会先把这些 URL **自动下载**到本机 `data/conductor/assets/`，得到本地文件路径。
3. **上传**：Playwright 打开小红书创作者中心后，用这些本地文件路径执行「选择文件 → 上传」，和真人选图上传一样，**自动完成上传和发布**。

素材尺寸说明：

- 当前文生图是 **1920×1920**，单张通常 1～3MB，**小于小红书单张 10MB 限制**，可以正常自动上传。
- 若某次生成的图过大（>10MB），发布逻辑会打一条 warning 日志，小红书可能上传失败，届时可在 pipeline 里加一步「上传前压缩」。
- 视频：目前自动发布只支持**图文笔记**（多张图）；若 `generated_assets` 里是视频 URL，需要后续支持「视频笔记」发布流程才会自动发视频。

---

## 常见问题

- **只存了草稿、没有发小红书**  
  检查 `.env` 里是否 `CONDUCTOR_AUTO_PUBLISH=true`，以及是否重启过 `python3 -m conductor`。

- **报错「小红书未登录」**  
  再跑一次 `python3 conductor/login_helper.py --wait 180`，在弹窗里完成登录。

- **报错 playwright 或 browser 相关**  
  确认 `pip install playwright`，且本机有 Chrome；用 `python3 -m conductor.test_browser` 自检。

- **不想自动发、只想生成草稿**  
  把 `CONDUCTOR_AUTO_PUBLISH` 设为 `false` 或删掉；发主题后仍会生成内容并存草稿，再在飞书里用「自动发布 &lt;id&gt; 小红书」手动触发发布。

- **显示发布成功但账号里看不到笔记**  
  发布逻辑已加「二次确认」点击（确认/确定/确认发布）；若仍看不到，请到创作者中心看：**草稿箱**（是否被当成草稿）、**笔记管理**（是否在审核中）。可对同一条再执行一次 `--republish <id>` 重试。

---

## 流程小结

```
飞书发「春天穿搭分享」
  → 自媒体助手收到消息，启动 Pipeline（auto_publish=true）
  → Scan → Ideate → Create（文案+可选配图）→ 存草稿
  → Publish：publish_draft() 发现 CONDUCTOR_AUTO_PUBLISH=true
  → 调用 publish_content(id, "xiaohongshu")
  → autopublish.publish_xiaohongshu() 用 Playwright 打开小红书并发布
  → 飞书结果卡片 + 小红书后台多一篇笔记
```

按上述前置条件准备好后，用飞书发一条主题即可完成「从飞书发需求到它自己发完一篇小红书」的一条龙测试。
