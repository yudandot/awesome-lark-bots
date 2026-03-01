# -*- coding: utf-8 -*-
"""
全局配置：环境变量、常量、路径。
所有需要用到的 API key、URL、阈值均在此集中管理。
"""

import logging
import os
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# 项目根目录 & 数据目录
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SENTIMENT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "sentiment"
CACHE_DIR = DATA_DIR / "cache"
REPORTS_DIR = DATA_DIR / "reports"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
SAMPLES_DIR = DATA_DIR / "samples"
EXPORT_DIR = DATA_DIR / "exports"

for _d in (CACHE_DIR, REPORTS_DIR, SNAPSHOTS_DIR, SAMPLES_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# API Keys & URLs
# ---------------------------------------------------------------------------
KIMI_API_KEY = os.getenv("KIMI_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
FEISHU_WEBHOOK_URL = os.getenv("SENTIMENT_FEISHU_WEBHOOK", "") or os.getenv("FEISHU_WEBHOOK", "")
JOA_TOKEN = os.getenv("JOA_TOKEN", "")
JOA_BASE = os.getenv("JOA_BASE_URL", "https://api.justoneapi.com")
BROWSER_MCP_HTTP_URL = os.getenv("BROWSER_MCP_HTTP_URL", "").strip()

# ---------------------------------------------------------------------------
# GitHub 数据存储
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

# ---------------------------------------------------------------------------
# 时区
# ---------------------------------------------------------------------------
BEIJING = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 采集参数
# ---------------------------------------------------------------------------
UNIFIED_MAX_PAGES = int(os.getenv("UNIFIED_MAX_PAGES", "20"))
PLATFORM_MAX_PAGES = int(os.getenv("PLATFORM_MAX_PAGES", "30"))
PLATFORM_PAGES_DEEP = {"douyin": 50, "xiaohongshu": 50, "kuaishou": 50}
MAX_POSTS = 5000
MIN_POSTS_BRAND_WEEKLY = 5000
KIMI_SAMPLE = 2000
MIN_PER_PLATFORM = 80
TARGET_DOUYIN = 450
TARGET_XHS = 400
TARGET_KUAISHOU = 450
REQ_DELAY = 0.4
WORKERS = 3

# ---------------------------------------------------------------------------
# AI 分析参数
# ---------------------------------------------------------------------------
KIMI_WEB_SUPPLEMENT_TARGET_CHARS = 5000
KIMI_REPORT_WEB_SEARCH = os.getenv("KIMI_REPORT_WEB_SEARCH", "").strip().lower() in ("1", "true", "yes")
KIMI_REPORT_TARGET_CHARS = 10000
KIMI_REPORT_MAX_TOKENS = 16384
MAX_POSTS_BLOCK_CHARS = 120_000

# ---------------------------------------------------------------------------
# 平台名映射
# ---------------------------------------------------------------------------
PLATFORM_CN = {
    "WEIBO": "微博", "DOUYIN": "抖音", "XIAOHONGSHU": "小红书",
    "BILIBILI": "B站", "KUAISHOU": "快手", "ZHIHU": "知乎",
    "NEWS": "新闻", "WEIXIN": "微信公众号", "TOUTIAO": "头条",
    "TIKTOK": "TikTok", "YOUTUBE": "YouTube",
    "TWITTER": "Twitter/X", "INSTAGRAM": "Instagram", "FACEBOOK": "Facebook",
    "TAOBAO": "淘宝", "PINDUODUO": "拼多多",
    "微博": "微博", "抖音": "抖音", "小红书": "小红书",
    "B站": "B站", "快手": "快手", "知乎": "知乎", "头条": "头条",
    "微信公众号": "微信公众号", "TikTok": "TikTok", "YouTube": "YouTube",
    "weibo": "微博", "douyin": "抖音", "xiaohongshu": "小红书",
    "bilibili": "B站", "kuaishou": "快手", "zhihu": "知乎",
    "toutiao": "头条", "weixin": "微信公众号",
    "tiktok": "TikTok", "youtube": "YouTube",
    "twitter": "Twitter/X", "instagram": "Instagram", "facebook": "Facebook",
    "taobao": "淘宝", "pinduoduo": "拼多多",
}

# 所有可用于深度搜索的平台（key → 中文名）
ALL_PLATFORMS = {
    "weibo": "微博",
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "bilibili": "B站",
    "kuaishou": "快手",
    "zhihu": "知乎",
    "toutiao": "头条",
    "weixin": "微信公众号",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "twitter": "Twitter/X",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "taobao": "淘宝",
    "pinduoduo": "拼多多",
}

# 默认用于舆情监控的国内平台
PLATFORMS_DEFAULT = ["weibo", "douyin", "xiaohongshu", "bilibili", "kuaishou", "zhihu"]

URL_DOMAIN_TO_PLATFORM = [
    ("weibo.com", "微博"), ("weibo.cn", "微博"),
    ("bilibili.com", "B站"), ("b23.tv", "B站"),
    ("iesdouyin.com", "抖音"), ("douyin.com", "抖音"),
    ("xiaohongshu.com", "小红书"), ("xhslink.com", "小红书"),
    ("kuaishou.com", "快手"),
    ("zhihu.com", "知乎"),
    ("ixigua.com", "头条"), ("toutiao.com", "头条"),
    ("mp.weixin.qq.com", "微信公众号"),
    ("tiktok.com", "TikTok"),
    ("youtube.com", "YouTube"), ("youtu.be", "YouTube"),
    ("twitter.com", "Twitter/X"), ("x.com", "Twitter/X"),
    ("instagram.com", "Instagram"),
    ("facebook.com", "Facebook"),
    ("taobao.com", "淘宝"), ("tmall.com", "淘宝"),
    ("pinduoduo.com", "拼多多"),
]

# ---------------------------------------------------------------------------
# 情感 & 停用词
# ---------------------------------------------------------------------------
POS_KW = frozenset(
    "好看 喜欢 不错 推荐 好玩 感动 开心 惊喜 可爱 治愈 温暖 期待 支持 "
    "优秀 精彩 满意 浪漫 绝美 神仙 好评 赞 棒 震撼 幸福 陪伴 温柔".split()
)
NEG_KW = frozenset(
    "垃圾 差评 坑 bug 崩溃 卡顿 退款 恶心 失望 无语 氪金 骗 烂 吐槽 "
    "闪退 举报 投诉 割韭菜 贵 差 崩 卡 黑心 敷衍 维权 炸服".split()
)
STOP_WORDS = frozenset(
    "的 了 是 在 我 你 他 她 它 和 有 就 也 都 不 吗 啊 呢 吧 "
    "这个 一个 什么 怎么 还是 可以 已经 自己 他们 我们 没有 "
    "知道 时候 现在 真的 比较 但是 如果 还有 因为 所以 而且 "
    "那个 这样 那样 然后 虽然 htt https com www".split()
)

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
_log_fmt = "%(asctime)s [%(levelname)s] %(message)s"
_log_level = getattr(logging, (os.getenv("LOG_LEVEL") or "INFO").upper(), logging.INFO)
_log_file = os.getenv("SENTIMENT_LOG_FILE", "").strip()
logging.basicConfig(level=_log_level, format=_log_fmt)
log = logging.getLogger("sentiment")
if _log_file:
    try:
        fh = logging.FileHandler(_log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_log_fmt))
        log.addHandler(fh)
    except OSError:
        pass
