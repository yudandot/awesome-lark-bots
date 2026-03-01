# -*- coding: utf-8 -*-
"""
批量翻译外语标题为中文。

策略：把同一区域的所有外语标题打包成一次 LLM 调用，
让 LLM 返回逐行对应的中文翻译，然后原地替换 title 字段。
对已经是中文的标题跳过。
"""

from __future__ import annotations

import re

from newsbot.config import log

# 简单的中文检测：包含 2 个以上 CJK 字符就认为是中文
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _is_mostly_chinese(text: str) -> bool:
    cjk = len(_CJK_RE.findall(text))
    return cjk >= max(2, len(text) * 0.15)


def _batch_translate(titles: list[str]) -> list[str]:
    """调用 LLM 批量翻译标题列表。"""
    from core.llm import chat_completion

    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))

    system = (
        "你是一个翻译机器。用户给你一组编号的新闻标题（可能是英语、越南语、日语、韩语、"
        "德语、法语、印尼语等），请逐条翻译为简洁的中文。\n\n"
        "规则：\n"
        "- 每行格式：编号. 中文翻译\n"
        "- 保持编号不变\n"
        "- 人名/地名/机构名可保留原文并附中文\n"
        "- 如果原文已经是中文，原样输出\n"
        "- 不要加任何额外解释"
    )

    try:
        result = chat_completion(
            provider="deepseek",
            system=system,
            user=numbered,
            temperature=0.1,
        )
    except Exception as e:
        log.warning("批量翻译失败: %s", e)
        return titles

    translated: dict[int, str] = {}
    for line in result.strip().split("\n"):
        line = line.strip()
        m = re.match(r"^(\d+)\.\s*(.+)$", line)
        if m:
            idx = int(m.group(1)) - 1
            translated[idx] = m.group(2).strip()

    out: list[str] = []
    for i, orig in enumerate(titles):
        out.append(translated.get(i, orig))
    return out


def translate_rss_titles(
    data: dict[str, list[dict]],
    title_key: str = "title",
) -> None:
    """
    原地翻译 RSS/Reddit 数据中的外语标题。
    data: {source_name: [{"title": ..., ...}, ...]}
    """
    to_translate: list[tuple[str, int, str]] = []

    for source, items in data.items():
        for i, item in enumerate(items):
            title = item.get(title_key, "")
            if title and not _is_mostly_chinese(title):
                to_translate.append((source, i, title))

    if not to_translate:
        return

    if len(to_translate) > 120:
        to_translate = to_translate[:120]

    titles_only = [t[2] for t in to_translate]

    BATCH = 40
    all_translated: list[str] = []
    for start in range(0, len(titles_only), BATCH):
        batch = titles_only[start:start + BATCH]
        result = _batch_translate(batch)
        all_translated.extend(result)

    for idx, (source, item_idx, _orig) in enumerate(to_translate):
        if idx < len(all_translated):
            data[source][item_idx][title_key] = all_translated[idx]

    log.info("翻译了 %d 条外语标题", len(to_translate))
