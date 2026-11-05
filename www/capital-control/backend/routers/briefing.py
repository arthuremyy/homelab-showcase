"""Briefing IA — collecte de contexte enrichie, génération (manuelle + scheduler), historique."""
import asyncio
import logging
from datetime import date, timedelta

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import db
from ai.briefing import build_briefing, get_fear_greed, TECHNICALS_CLASSES
from analysis.technicals import compute_all_indicators
from providers.market_data import get_crypto_history
from providers.stocks import get_stock_history, get_market_indices
from providers.news import get_portfolio_news, get_market_news
from services import valuation, pricing, history

logger = logging.getLogger("capital.briefing")
router = APIRouter(prefix="/api")

_generate_lock = asyncio.Lock()


async def _asset_series(p: dict) -> list[float]:
    """Série de prix ~1 an pour un actif (indicateurs + stats 52 semaines)."""
    if p["asset_type"] == "crypto" and p.get("coingecko_id"):
        hist = await get_crypto_history(p["coingecko_id"], 365, "eur")
        return [x[1] for x in hist.get("prices", [])]
    if p.get("ticker"):
        hist = await get_stock_history(p["ticker"], "1y")
        return [x["value"] for x in hist]
    return []


def _series_stats(prices: list[float]) -> dict:
    """Perf 1M/3M + distance au plus-haut/plus-bas 52 semaines (série ~quotidienne)."""
    if len(prices) < 20:
        return {}
    current = prices[-1]
    high, low = max(prices), min(prices)

    def perf(days_back: int) -> float | None:
        idx = len(prices) - 1 - days_back
        if idx < 0 or not prices[idx]:
            return None
        return round((current - prices[idx]) / prices[idx] * 100, 2)

    return {
        "perf_30d": perf(min(30, len(prices) - 1)),
        "perf_90d": perf(min(90, len(prices) - 1)),
        "pct_from_high": round((current - high) / high * 100, 2) if high else None,
        "pct_from_low": round((current - low) / low * 100, 2) if low else None,
    }


async def _positions_analysis(positions: list[dict]) -> tuple[dict, dict]:
    """(indicators, asset_stats) — indicateurs seulement pour les classes pertinentes,
    stats 52 semaines pour tout ce qui a un historique."""
    open_pos = [p for p in positions if not p["closed"]]

    async def one(p):
        try:
            prices = await _asset_series(p)
        except Exception as e:
            logger.warning(f"series error {p['isin']}: {e}")
            return p["isin"], None, {}
        ind = None
        if (p.get("asset_class") or "equity") in TECHNICALS_CLASSES and len(prices) >= 30:
            ind = compute_all_indicators(prices[-120:])
        return p["isin"], ind, _series_stats(prices)

    results = await asyncio.gather(*[one(p) for p in open_pos])
    indicators = {isin: ind for isin, ind, _ in results if ind}
    stats = {isin: st for isin, _, st in results if st}
    return indicators, stats


def _prev_briefing_context() -> dict | None:
    prev = db.get_briefing(0)
    if not prev:
        return None
    c = prev.get("content", {})
    return {
        "date": prev.get("date"),
        "sentiment": c.get("market_sentiment"),
        "sentiment_score": c.get("sentiment_score"),
        "summary": c.get("summary"),
        "conseil_du_jour": c.get("conseil_du_jour"),
    }


def _recent_activity() -> tuple[list[dict], list[dict]]:
    """(transactions 14 jours, alertes 7 jours)."""
    since_tx = (date.today() - timedelta(days=14)).isoformat()
    since_al = (date.today() - timedelta(days=7)).isoformat()
    with db.connect() as conn:
        txs = db.rows(conn.execute(
            "SELECT date, type, isin, name, shares, price, amount, note FROM transactions "
            "WHERE date >= ? AND source != 'reprise' ORDER BY date DESC LIMIT 20", (since_tx,)))
        events = db.rows(conn.execute(
            "SELECT message, fired_at FROM alert_events WHERE fired_at >= ? "
            "ORDER BY id DESC LIMIT 10", (since_al,)))
    return txs, events


async def generate_and_store() -> dict:
    """Pipeline complet : prix frais → contexte enrichi → LLM → sauvegarde."""
    async with _generate_lock:
        await pricing.update_all_prices(include_stocks=True)
        summary = valuation.portfolio_summary()
        positions = summary["positions"]

        assets = {a["isin"]: a for a in db.get_all_assets()}
        news_assets = [assets[p["isin"]] for p in positions
                       if not p["closed"] and p["isin"] in assets]
        recent_txs, alert_events = _recent_activity()

        (indicators, asset_stats), indices, news, fear_greed = await asyncio.gather(
            _positions_analysis(positions),
            get_market_indices(),
            get_portfolio_news(news_assets) if news_assets
            else get_market_news("bourse investissement économie", "fr", 15),
            get_fear_greed(),
        )

        ctx = {
            "summary": summary,
            "positions": positions,
            "indicators": indicators,
            "asset_stats": asset_stats,
            "indices": indices if isinstance(indices, dict) else {},
            "news": news if isinstance(news, list) else [],
            "fear_greed": fear_greed if isinstance(fear_greed, dict) else None,
            "prev_briefing": _prev_briefing_context(),
            "variations": {"7d": history.variation(7), "30d": history.variation(30)},
            "recent_txs": recent_txs,
            "alert_events": alert_events,
            "pea": valuation.pea_status(),
        }

        result = await build_briefing(ctx)
        if result.get("status") == "ok":
            db.save_briefing(result["briefing"])
        return result


@router.get("/briefing")
async def get_briefing(offset: int = 0):
    briefing = db.get_briefing(max(0, offset))
    if briefing:
        return {"status": "ok", **briefing}
    return {"status": "empty",
            "message": "Aucun briefing. Génération automatique chaque semaine, ou bouton Générer."}


@router.post("/briefing/generate")
async def generate_briefing():
    try:
        return await generate_and_store()
    except Exception as e:
        logger.error(f"briefing generate error: {e}")
        return JSONResponse(status_code=502, content={"error": str(e)})
