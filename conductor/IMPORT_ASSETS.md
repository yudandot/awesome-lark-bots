# 自带素材入库 — 把本地图片/图文放进内容仓库并发布

你可以把自己的图片（或后续支持的视频）放进一个目录，配上标题和正文，导入到内容仓库后由机器人自动发布到小红书，无需走「选题 → 创意 → 火山出图」流程。

---

## 1. 准备一个目录

在项目下随便建一个目录，例如：

```text
data/conductor/imports/我的活动图/
```

或任意路径，例如：

```text
~/Desktop/待发小红书/
```

---

## 2. 放入素材和文案

在**同一目录**里放：

- **图片**：至少一张，支持 `.png` / `.jpg` / `.jpeg` / `.webp`（文件名随意，不要用 `content.json` / `content.md` 当图片名即可）。
- **文案**（三选一）：
  - **方式 A：content.json**  
    同目录下新建 `content.json`：
    ```json
    {
      "title": "你的标题（可带 emoji）",
      "body": "正文内容，可以多行。",
      "hashtags": ["#标签1", "#标签2"]
    }
    ```
  - **方式 B：content.md**  
    同目录下新建 `content.md`：第一行当标题，后面都是正文。
    ```markdown
    你的标题（可带 emoji）
    正文第一段。
    正文第二段。
    ```
  - **方式 C：命令行参数**  
    不建 `content.json` / `content.md`，用 `--title` 和 `--body` 直接传：
    ```bash
    python3 -m conductor.cli --import-dir ./data/conductor/imports/我的活动图/ \
      --title "标题" --body "正文"
    ```

若**既没有 content.json/content.md，也没有 --title/--body**，可以传 **`--brief "一句话描述"`**，由 LLM 根据这句话生成标题和正文（需要配置 DeepSeek 等）。

---

## 3. 执行入库（可选直接发布）

在项目根目录执行：

```bash
# 只入库，不发布（之后可在飞书里「自动发布 <id> 小红书」或再跑一次带 --publish）
PYTHONPATH=. python3 -m conductor.cli --import-dir data/conductor/imports/我的活动图/

# 入库并立即发布到小红书
PYTHONPATH=. python3 -m conductor.cli --import-dir data/conductor/imports/我的活动图/ --publish
```

若用了 `--brief` 且没有 content.json/content.md：

```bash
PYTHONPATH=. python3 -m conductor.cli --import-dir ./我的图片目录/ --brief "周末咖啡馆打卡，氛围感拉满" --publish
```

执行后会：

1. 把该目录下的图片路径和文案写入内容仓库（生成一条新内容，有 `content_id`）。
2. 若加了 `--publish`，会立刻调 Playwright 打开小红书并发布（需本机已登录创作者中心）。

---

## 4. 小结

| 你有         | 做法 |
|--------------|------|
| 图片 + 自己写标题/正文 | 目录里放图片 + `content.json` 或 `content.md`，然后 `--import-dir 目录 [--publish]`。 |
| 图片 + 只想到一句话   | 用 `--import-dir 目录 --brief "一句话" [--publish]`，由 LLM 生成标题和正文。 |
| 只有图片            | 用 `--import-dir 目录 --title "标题" --body "正文" [--publish]`，或先写 content.json 再导入。 |

入库后，在飞书里对自媒体助手说「草稿」可以看到新内容，说「自动发布 &lt;content_id&gt; 小红书」也可以再发一次。
