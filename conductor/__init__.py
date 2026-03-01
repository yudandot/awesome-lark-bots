# -*- coding: utf-8 -*-
"""
conductor/ — 自媒体助手：自主编排内容全流程。
================================================

这是 AIlarkteams 的第六个机器人（也是最核心的一个）。
它不自己写内容，而是**编排**其他模块完成从灵感到发布的完整链路：

  感知(Scan) → 构思(Ideate) → 创作(Create) → 发布(Publish) → 互动(Engage) → 复盘(Review)

每个阶段对应一个 Stage 模块，Pipeline 引擎按顺序或定时执行。

运行：python3 -m conductor
"""
