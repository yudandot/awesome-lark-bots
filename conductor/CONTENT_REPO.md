# 内容仓库

所有生成的内容都会存进**内容仓库**，方便囤稿、统一管理和按需发布。

---

## 仓库位置

- **目录**：`data/conductor/content/`
- **格式**：每条内容一个 JSON 文件，如 `2054b0616dcb.json`
- **字段**：标题、各平台文案、视觉 Prompt、生成素材 URL、状态、发布时间等

---

## 状态说明

| 状态 | 含义 |
|------|------|
| **draft** | 草稿（刚生成，未审批） |
| **ready** | 待发布（已审批通过） |
| **scheduled** | 已设定时发布 |
| **published** | 已发布到平台 |
| **failed** | 发布失败（可修好后重新发布） |

---

## 怎么囤内容

1. **关掉自动发布**：在 `.env` 里设 `CONDUCTOR_AUTO_PUBLISH=false`（或不设），这样每次跑 pipeline 只会生成并**存入仓库**，不会自动发到小红书。
2. **正常跑流程**：飞书发主题或 CLI 跑 `--topic "xxx"`，生成的内容都会以草稿形式进仓库。
3. **查看仓库**：
   ```bash
   python3 -m conductor.cli --list
   ```
4. **按需发布**：挑一条要发的，用 `--republish <content_id>` 发到小红书；或在飞书里对自媒体助手说「自动发布 &lt;id&gt; 小红书」。

---

## 常用命令

```bash
# 列出仓库里所有内容（按时间倒序）
python3 -m conductor.cli --list

# 只看草稿（囤着未发的）
python3 -m conductor.cli --list --status draft

# 查看某条详情（文案、Prompt、素材链接）
python3 -m conductor.cli --detail <content_id>

# 把某条重新发到小红书
python3 -m conductor.cli --republish <content_id>
```

---

## 飞书里怎么用

- **草稿** / **草稿箱**：看当前仓库列表
- **详情 &lt;id&gt;**：看该条标题、文案、视觉 Prompt、已生成素材链接
- **自动发布 &lt;id&gt; 小红书**：把这条发到小红书（会先下载素材再自动上传发布）
