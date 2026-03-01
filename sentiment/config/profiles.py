# -*- coding: utf-8 -*-
"""
报告配置（profiles）和账号配置（accounts）。
集中管理各种报告类型的参数和月度统计需要的账号信息。
"""

# ---------------------------------------------------------------------------
# 舆情报告配置
# ⚠️ 以下为示例配置，请根据你自己的品牌和需求进行自定义修改。
# ---------------------------------------------------------------------------
REPORT_PROFILES = {
    # 示例：品牌周报（请替换为你自己的品牌关键词）
    "brand-weekly": {
        "id": "brand-weekly",
        "title": "品牌舆情周报",
        "subject": "我的品牌",
        "keywords": ["我的品牌", "mybrand"],
        "days": 7,
        "max_posts": 5000,
        "kimi_sample": 2000,
        "web_supplement": True,
    },
    # 示例：子品牌/子账号双周报
    "sub-brand-biweek": {
        "id": "sub-brand-biweek",
        "title": "子品牌 双周报",
        "subject": "子品牌",
        "keywords": ["子品牌"],
        "days": 14,
        "max_posts": 2500,
        "kimi_sample": 2000,
        "web_supplement": False,
    },
}

# ---------------------------------------------------------------------------
# 月度统计账号配置
# ⚠️ 示例配置，请替换为你自己的品牌账号信息。
# ---------------------------------------------------------------------------
ACCOUNTS = [
    {
        "key": "official",
        "name": "品牌官方账号",
        "keywords": ["我的品牌官方"],
        "platform_ids": {},
    },
    {
        "key": "founder",
        "name": "创始人账号",
        "keywords": ["创始人姓名"],
        "platform_ids": {},
    },
]

TOPIC_EXPOSURE_KEYWORDS = ["我的品牌"]


def get_profile(profile_id: str) -> dict:
    """获取报告配置，不存在则返回第一个 profile。"""
    default_key = next(iter(REPORT_PROFILES))
    return REPORT_PROFILES.get(profile_id, REPORT_PROFILES[default_key])
