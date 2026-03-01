# -*- coding: utf-8 -*-
"""
research/search.py — 联网搜索工具层

提供三种搜索能力：
  - web_search()  : 网页搜索（优先 Tavily，fallback DuckDuckGo）
  - news_search() : 新闻搜索（DuckDuckGo News）
  - fetch_url()   : 抓取网页正文（用于深入阅读搜索结果）

搜索后端优先级：
  1. Tavily — 为 AI Agent 设计，结果质量高，需要 TAVILY_API_KEY（免费 1000 次/月）
  2. DuckDuckGo — 完全免费，零配置，作为兜底
"""

import os
import logging

import requests as _requests

log = logging.getLogger("research")


# ── Tavily（推荐） ──────────────────────────────────────────

def tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Tavily API — 高质量搜索，自带 AI 摘要。"""
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = _requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        if data.get("answer"):
            results.append({"title": "AI Summary", "content": data["answer"], "url": ""})
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "url": r.get("url", ""),
            })
        return results
    except Exception as e:
        log.warning("Tavily search failed: %s", e)
        return []


# ── DuckDuckGo（免费兜底，用 requests 直接调 API）────────────

_DDGS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


def _ddgs_text(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo HTML 搜索：零依赖，用 requests + BeautifulSoup 解析。"""
    try:
        resp = _requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=_DDGS_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        for item in soup.select(".result")[:max_results]:
            title_tag = item.select_one(".result__a")
            snippet_tag = item.select_one(".result__snippet")
            if not title_tag:
                continue
            url = title_tag.get("href", "")
            if url.startswith("//duckduckgo.com/l/"):
                import urllib.parse
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                url = parsed.get("uddg", [url])[0]
            results.append({
                "title": title_tag.get_text(strip=True),
                "content": snippet_tag.get_text(strip=True) if snippet_tag else "",
                "url": url,
            })
        return results
    except Exception as e:
        log.warning("DuckDuckGo search failed: %s", e)
        return []


def _ddgs_news(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo 新闻搜索：通过 HTML 接口获取。"""
    try:
        resp = _requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"{query} news", "ia": "news"},
            headers=_DDGS_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        for item in soup.select(".result")[:max_results]:
            title_tag = item.select_one(".result__a")
            snippet_tag = item.select_one(".result__snippet")
            if not title_tag:
                continue
            url = title_tag.get("href", "")
            if url.startswith("//duckduckgo.com/l/"):
                import urllib.parse
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                url = parsed.get("uddg", [url])[0]
            results.append({
                "title": title_tag.get_text(strip=True),
                "content": snippet_tag.get_text(strip=True) if snippet_tag else "",
                "url": url,
                "date": "",
            })
        return results
    except Exception as e:
        log.warning("DuckDuckGo news search failed: %s", e)
        return []


# ── 网页正文抓取 ────────────────────────────────────────────

def fetch_url(url: str, max_chars: int = 8000) -> str:
    """抓取网页并提取正文，用于深入阅读搜索结果。"""
    try:
        resp = _requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ResearchBot/1.0"},
        )
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        clean = "\n".join(lines)
        return clean[:max_chars]
    except Exception as e:
        return f"Error fetching URL: {e}"


# ── 对外统一接口 ────────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> list[dict]:
    """网页搜索：优先 Tavily，无 API Key 则用 DuckDuckGo。"""
    if os.environ.get("TAVILY_API_KEY", "").strip():
        results = tavily_search(query, max_results)
        if results:
            return results
    return _ddgs_text(query, max_results)


def news_search(query: str, max_results: int = 5) -> list[dict]:
    """新闻搜索：使用 DuckDuckGo News。"""
    return _ddgs_news(query, max_results)
