# 电脑休眠时如何自动发布

本机休眠后，进程会挂起，**无法**在本机执行定时发布。要让「到点自动发布」在休眠时也执行，需要把**触发逻辑**放到一台 24/7 运行的机器上，由外部定时去调用。

## 思路

1. 在一台**一直开机**的机器上（如 VPS、云主机、树莓派、家里 NAS）运行 **conductor 定时触发 HTTP 服务**。
2. 用**外部 cron 服务**（如 [cron-job.org](https://cron-job.org)、GitHub Actions 定时任务）每 15～30 分钟请求该服务的 `/cron` 接口。
3. 服务收到请求后执行：**检查定时发布队列 → 到点则发布**（与本地 `Scheduler` 里的逻辑一致）。

这样**不依赖本机是否休眠**，只要运行 cron_server 的那台机器在线即可。

---

## 步骤一：准备一台 24/7 的机器

- **推荐**：云服务器（阿里云 / 腾讯云 / 海外 VPS 等），或家里长期开机的电脑 / NAS。
- 该机器需要：
  - 能跑 Python 3 + 本项目（conductor 依赖）
  - 若要做「自动发布到小红书」，需安装 **Playwright + Chrome**，并在该机器上**至少登录一次**小红书创作者中心（登录态会保存在该机的用户目录）。
  - 能对外提供 HTTP（若用公网 cron 调用，需有公网 IP 或内网穿透）。

---

## 步骤二：在本项目里配置并启动 HTTP 服务

1. **复制项目与配置**  
   在该机器上拉取/复制本仓库，配置 `.env`（至少包含：飞书/LLM/火山等用到的 key；若要做发布，还需 Playwright 能连到已登录的 Chrome 或使用无头登录态）。

2. **设置定时触发的 token**（必选，防止被随意调用）  
   在 `.env` 中增加：
   ```bash
   CONDUCTOR_CRON_TOKEN=你的随机字符串
   ```
   例如：`CONDUCTOR_CRON_TOKEN=my_secret_trigger_abc123`

3. **启动定时触发服务**  
   在该机器上执行：
   ```bash
   cd /path/to/AIlarkteams
   PYTHONPATH=. python3 -m conductor.cron_server --port 8765
   ```
   默认监听 `0.0.0.0:8765`。如需改端口：`--port 其他端口`。

4. **自测**  
   - 健康检查：`curl http://本机IP:8765/health`  
   - 触发一次（只做「检查定时发布」）：  
     `curl "http://本机IP:8765/cron?token=你的CONDUCTOR_CRON_TOKEN"`  
   - 若还要顺带执行「当日定时选题+生成」：  
     `curl "http://本机IP:8765/cron?token=你的CONDUCTOR_CRON_TOKEN&scan=1"`

---

## 步骤三：用外部 cron 定期请求

在 [cron-job.org](https://cron-job.org) 或类似服务中：

- **URL**：`https://你的服务器公网IP或域名:8765/cron?token=你的CONDUCTOR_CRON_TOKEN`
- **方法**：GET
- **间隔**：建议每 15 分钟或 30 分钟（与本地 Scheduler 里「每 30 分钟检查定时发布」对齐即可）。

若希望**每天在固定时间再执行一次「定时选题+生成」**，可再建一条 cron，URL 加上 `&scan=1`，并设为每天一次（时间与 `CONDUCTOR_SCHEDULE_SCAN_TIMES` 一致）。

---

## 数据与发布环境说明

- **内容仓库**：定时发布会从 `data/conductor/content/` 读「已设置定时时间」的内容。若内容是在本机生成的，需要把该目录**同步到运行 cron_server 的那台机器**（如 rsync、网盘、Git 等），否则那台机器上看不到你的定时条数。
- **发布执行**：发布动作（如小红书）是在**运行 cron_server 的机器上**执行的（调用 Playwright）。因此该机需已安装 Playwright/Chrome，并完成过一次小红书登录；或通过 `CHROME_CDP_URL` 连到已登录的 Chrome。
- **仅本机跑、不部署到服务器**：若只在本机跑 conductor、不部署到 24/7 机器，则**电脑休眠期间无法自动发布**；只能在本机唤醒后由本机 Scheduler 或再次运行 conductor 时补跑。

---

## 小结

| 场景 | 做法 |
|------|------|
| 电脑常开 | 本机 `python3 -m conductor` 带 Scheduler 即可，无需 cron_server。 |
| 电脑会休眠，希望到点照常发 | 在 24/7 机器上跑 `conductor.cron_server`，用外部 cron 定期请求 `/cron?token=xxx`；内容仓库与发布环境需在该机可用。 |
