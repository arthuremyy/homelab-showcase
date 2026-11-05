"""
Provider: Actualités financières v2.
Sources : Yahoo Finance RSS (par ticker) + Google News RSS.
v2 : requêtes courtes (news_query du registre), filtre fraîcheur 7 j, dédup par titre
normalisé, cache TTL 15 min, tag par sujet pour le scoring de pertinence.
"""
import asyncio
import logging
import re
import time
import defusedxml.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger("capital.news")

_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

MAX_AGE_DAYS = 7
CACHE_TTL = 900

_cache: dict[str, tuple[list, float]] = {}
_locks: dict[str, asyncio.Lock] = {}

# Requêtes macro par classe d'actif (fallback quand la requête ciblée est pauvre)
CLASS_QUERIES = {
    "etf": "marchés actions MSCI World ETF",
    "monetary": "BCE taux directeurs marché monétaire",
    "crypto": "Bitcoin crypto marché",
    "equity": None,   # la requête ciblée suffit pour une action
}

MACRO_QUERIES = [
    ("CAC40 bourse marchés financiers", 5),
    ("économie inflation taux BCE", 4),
]


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _parse_rss_date(date_str: str) -> str:
    try:
        return parsedate_to_datetime(date_str).isoformat()
    except Exception:
        return date_str


def _is_fresh(published: str) -> bool:
    try:
        dt = datetime.fromisoformat(published)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt < timedelta(days=MAX_AGE_DAYS)
    except Exception:
        return False   # date illisible = rejeté (la fraîcheur est la règle)


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:80]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")[:200].strip()


async def _yahoo_rss(ticker: str, topic: str, max_results: int = 4) -> list[dict]:
    if not ticker or ticker.startswith("0P"):   # tickers fonds Morningstar : flux vide
        return []
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=FR&lang=fr-FR"
    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except Exception as e:
        logger.warning(f"Yahoo RSS error for {ticker}: {e}")
        return []

    articles = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        articles.append({
            "title": title,
            "link": link,
            "published": _parse_rss_date(item.findtext("pubDate", "")),
            "source": "Yahoo Finance",
            "topic": topic,
            "score": 3,
            "description": _strip_html(item.findtext("description", "")),
        })
        if len(articles) >= max_results:
            break
    return articles


async def _google_news_rss(query: str, topic: str, score: int,
                           max_results: int = 6, lang: str = "fr") -> list[dict]:
    url = (f"https://news.google.com/rss/search"
           f"?q={quote_plus(query)}+when:7d&hl={lang}&gl=FR&ceid=FR:{lang}")
    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except Exception as e:
        logger.warning(f"Google News RSS error ({query}): {e}")
        return []

    articles = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title:
            continue
        source_el = item.find("source")
        source = source_el.text if source_el is not None else "Google News"
        if " - " in title and source_el is not None:
            title, source = title.rsplit(" - ", 1)
        articles.append({
            "title": title.strip(),
            "link": link,
            "published": _parse_rss_date(item.findtext("pubDate", "")),
            "source": source,
            "topic": topic,
            "score": score,
            "description": _strip_html(item.findtext("description", "")),
        })
        if len(articles) >= max_results:
            break
    return articles


def _merge(batches: list, limit: int = 20) -> list[dict]:
    """Fusion : fraîcheur obligatoire, dédup par titre normalisé + lien, tri score puis date."""
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    merged: list[dict] = []
    for batch in batches:
        if not isinstance(batch, list):
            continue
        for a in batch:
            if not _is_fresh(a.get("published", "")):
                continue
            link, title_key = a.get("link", ""), _norm_title(a.get("title", ""))
            if (link and link in seen_links) or (title_key and title_key in seen_titles):
                continue
            seen_links.add(link)
            seen_titles.add(title_key)
            merged.append(a)
    merged.sort(key=lambda a: (-a.get("score", 0), a.get("published", "")), reverse=False)
    # tri final : score desc, puis date desc
    merged.sort(key=lambda a: a.get("published", ""), reverse=True)
    merged.sort(key=lambda a: -a.get("score", 0))
    return merged[:limit]


async def get_market_news(query: str, lang: str = "fr", max_results: int = 10) -> list[dict]:
    """News générales sur requête libre (avec cache)."""
    key = f"q:{query}:{lang}"
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[1] < CACHE_TTL:
        return cached[0]
    async with _get_lock(key):
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[1] < CACHE_TTL:
            return cached[0]
        articles = _merge([await _google_news_rss(query, "Recherche", 2, max_results, lang)])
        _cache[key] = (articles, time.monotonic())
    return articles


async def get_portfolio_news(assets: list[dict]) -> list[dict]:
    """
    News ciblées portefeuille. `assets` : lignes du registre (name, ticker,
    asset_type, asset_class, news_query).
    """
    sig = ",".join(sorted(a.get("isin") or a.get("name", "") for a in assets))
    key = f"pf:{sig}"
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[1] < CACHE_TTL:
        return cached[0]

    async with _get_lock(key):
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[1] < CACHE_TTL:
            return cached[0]

        tasks = []
        seen_queries: set[str] = set()
        for a in assets[:10]:
            topic = a.get("name", "")[:40]
            if a.get("ticker"):
                tasks.append(_yahoo_rss(a["ticker"], topic))
            q = (a.get("news_query") or "").strip()
            if q and q.lower() not in seen_queries:
                seen_queries.add(q.lower())
                tasks.append(_google_news_rss(f"{q} bourse", topic, 3, 4))
            cq = CLASS_QUERIES.get(a.get("asset_class") or "")
            if cq and cq.lower() not in seen_queries:
                seen_queries.add(cq.lower())
                tasks.append(_google_news_rss(cq, "Marché", 1, 3))

        for q, n in MACRO_QUERIES:
            tasks.append(_google_news_rss(q, "Marché", 1, n))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        articles = _merge(list(results))
        _cache[key] = (articles, time.monotonic())

    return articles
