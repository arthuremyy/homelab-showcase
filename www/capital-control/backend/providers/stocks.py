"""Provider: Prix actions/ETF via Yahoo Finance (gratuit, pas de clé)."""
import logging

import httpx

logger = logging.getLogger("capital.stocks")

YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

import asyncio
import time

# Cache prix actions : {ticker: (data, ts)}
_price_cache: dict[str, tuple[dict, float]] = {}
_PRICE_TTL = 60  # secondes


def _previous_close(result: dict) -> float:
    """Clôture de la veille : avant-dernière de la série quotidienne.
    `chartPreviousClose` précède toute la fenêtre de 5 jours, pas la veille."""
    meta = result["meta"]
    try:
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    except (KeyError, IndexError, TypeError):
        closes = []
    if len(closes) >= 2:
        return closes[-2]
    return meta.get("previousClose", meta.get("chartPreviousClose", 0))


async def get_stock_price(ticker: str) -> dict | None:
    """Prix actuel d'une action/ETF via Yahoo Finance."""
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        try:
            resp = await client.get(
                f"{YF_BASE}/{ticker}",
                params={"interval": "1d", "range": "5d"},
            )
            resp.raise_for_status()
            data = resp.json()
            result = data["chart"]["result"][0]
            meta = result["meta"]
            return {
                "ticker": ticker,
                "name": meta.get("shortName") or meta.get("longName") or ticker,
                "price": meta["regularMarketPrice"],
                "previous_close": _previous_close(result),
                "currency": meta.get("currency", "EUR"),
            }
        except Exception as e:
            logger.error(f"Yahoo Finance error for {ticker}: {e}")
            return None


async def get_all_stock_prices(tickers: list[str]) -> dict:
    """Prix de tous les tickers, en parallèle, avec cache TTL 60 s."""
    now = time.monotonic()
    result: dict = {}
    to_fetch: list[str] = []

    for t in tickers:
        cached = _price_cache.get(t)
        if cached and (now - cached[1]) < _PRICE_TTL:
            result[t] = cached[0]
        else:
            to_fetch.append(t)

    if to_fetch:
        fetched = await asyncio.gather(
            *[get_stock_price(t) for t in to_fetch],
            return_exceptions=True,
        )
        for t, data in zip(to_fetch, fetched):
            if isinstance(data, dict) and data:
                _price_cache[t] = (data, now)
                result[t] = data
    return result


_PERIOD_INTERVAL = {
    "1d": "5m", "5d": "15m", "7d": "1h",
    "1mo": "1d", "3mo": "1d", "6mo": "1d",
    "1y": "1d", "2y": "1d", "5y": "1wk",
}


MACRO_TICKERS = {
    "CAC 40": "^FCHI",
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "VIX (volatilité)": "^VIX",
    "Taux US 10 ans": "^TNX",
    "EUR/USD": "EURUSD=X",
    "Or (once $)": "GC=F",
    "Brent ($)": "BZ=F",
}


async def get_market_indices() -> dict:
    """Contexte macro élargi pour le briefing : indices, VIX, taux, or, pétrole."""
    results = await asyncio.gather(
        *[get_stock_price(t) for t in MACRO_TICKERS.values()],
        return_exceptions=True,
    )
    out = {}
    for (name, _), data in zip(MACRO_TICKERS.items(), results):
        if isinstance(data, dict) and data:
            out[name] = {"price": data["price"], "previous_close": data["previous_close"]}
    return out


async def get_stock_history(ticker: str, period: str = "3mo") -> list:
    """Historique de prix pour graphiques (granularité auto selon la période).
    Fallback automatique sur l'intervalle journalier si l'intraday échoue.
    """
    interval = _PERIOD_INTERVAL.get(period, "1d")
    headers = {"User-Agent": "Mozilla/5.0"}

    async def _fetch(itv: str) -> list:
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            resp = await client.get(
                f"{YF_BASE}/{ticker}",
                params={"interval": itv, "range": period},
            )
            resp.raise_for_status()
            data = resp.json()
            result = data["chart"]["result"]
            if not result:
                return []
            timestamps = result[0].get("timestamp") or []
            closes = result[0]["indicators"]["quote"][0].get("close") or []
            return [
                {"time": ts, "value": c}
                for ts, c in zip(timestamps, closes)
                if c is not None
            ]

    try:
        rows = await _fetch(interval)
        # Fallback daily si l'intervalle intraday ne retourne rien
        if not rows and interval not in ("1d", "1wk"):
            rows = await _fetch("1d")
        return rows
    except Exception as e:
        logger.error(f"Yahoo history error for {ticker}: {e}")
        # Dernier recours : journalier
        if interval != "1d":
            try:
                return await _fetch("1d")
            except Exception:
                pass
        return []


async def get_daily_closes(ticker: str, start: str) -> dict[str, float]:
    """Clôtures quotidiennes depuis `start` (YYYY-MM-DD) → {date ISO: clôture}."""
    from datetime import date, datetime, timezone
    p1 = int(datetime.combine(date.fromisoformat(start), datetime.min.time(), timezone.utc).timestamp())
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = await client.get(f"{YF_BASE}/{ticker}",
                                params={"interval": "1d", "period1": p1, "period2": int(time.time())})
        resp.raise_for_status()
        result = resp.json()["chart"]["result"]
    if not result:
        return {}
    ts = result[0].get("timestamp") or []
    closes = result[0]["indicators"]["quote"][0].get("close") or []
    return {datetime.fromtimestamp(t, timezone.utc).date().isoformat(): c
            for t, c in zip(ts, closes) if c is not None}
