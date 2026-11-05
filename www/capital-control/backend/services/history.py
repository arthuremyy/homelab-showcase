"""
Historique du patrimoine — recalculé à partir des transactions et des cours passés.

Un mouvement ajouté après coup (rattrapage de pointage, avis Natixis) corrige donc toute la
courbe, au lieu de créer un saut le jour de la saisie. Stockage : portfolio_snapshots (une ligne
par jour, réécrite à chaque reconstruction).
"""
import asyncio
import json
import logging
import time
from datetime import date, timedelta

import db
from providers.market_data import get_crypto_history
from providers.stocks import get_daily_closes
from services.valuation import group_transactions, replay

logger = logging.getLogger("capital.history")

RANGES = {"1m": 31, "3m": 92, "1y": 366, "max": None}
_CLOSES_TTL = 3600
_closes_cache: dict[tuple, tuple[float, dict]] = {}
_lock = asyncio.Lock()
_pending: asyncio.Task | None = None


async def closes_for(asset: dict, start: str) -> dict[str, float]:
    """Clôtures quotidiennes {date: prix EUR} d'un actif depuis `start` (cache 1 h)."""
    key = (asset["isin"], start)
    hit = _closes_cache.get(key)
    if hit and time.monotonic() - hit[0] < _CLOSES_TTL:
        return hit[1]
    out: dict[str, float] = {}
    try:
        if asset["asset_type"] == "crypto" and asset.get("coingecko_id"):
            days = (date.today() - date.fromisoformat(start)).days + 2
            data = await get_crypto_history(asset["coingecko_id"], max(days, 2), "eur")
            for ts, price in data.get("prices", []):
                out[date.fromtimestamp(ts / 1000).isoformat()] = price   # dernier point du jour
        elif asset.get("ticker") and (asset.get("currency") or "EUR") == "EUR":
            out = await get_daily_closes(asset["ticker"], start)
    except Exception as e:
        logger.warning(f"Cours passés indisponibles pour {asset['isin']} : {e}")
    _closes_cache[key] = (time.monotonic(), out)
    return out


def _price_series(closes: dict[str, float], txs: list[dict], days: list[str],
                  last_price: float | None) -> dict[str, float]:
    """Prix de chaque jour : clôture, sinon dernier prix connu (clôture ou prix d'une transaction)."""
    known = dict(closes)
    for t in txs:
        if t.get("price") and t["date"] not in known:
            known[t["date"]] = t["price"]
    out, current = {}, None
    for d in days:
        if d in known:
            current = known[d]
        out[d] = current if current is not None else last_price
    if last_price and days and days[-1] == date.today().isoformat():
        out[days[-1]] = last_price       # aujourd'hui : le prix courant, pas la clôture de la veille
    return out


async def rebuild() -> int:
    """Recalcule toute la série depuis la première transaction. Retourne le nombre de jours."""
    async with _lock:
        txs = db.get_transactions()
        if not txs:
            return 0
        start = min(t["date"] for t in txs)
        first, today = date.fromisoformat(start), date.today()
        days = [(first + timedelta(n)).isoformat() for n in range((today - first).days + 1)]

        assets = {a["isin"]: a for a in db.get_all_assets()}
        prices = db.get_prices()
        groups = group_transactions(txs)
        isins = {isin for isin, _ in groups}
        closes = dict(zip(isins, await asyncio.gather(
            *[closes_for(assets.get(i, {"isin": i, "asset_type": "fund"}), start) for i in isins])))
        series = {i: _price_series(closes[i], [t for (j, _), g in groups.items() if j == i for t in g],
                                   days, (prices.get(i) or {}).get("price_eur"))
                  for i in isins}
        cash = sum(a["cash"] or 0 for a in db.get_accounts())

        rows = []
        for d in days:
            total = invested = 0.0
            by_account: dict[str, float] = {}
            for (isin, account), group in groups.items():
                s = replay(group, as_of=d)
                if not s["shares"]:
                    continue
                v = s["shares"] * (series[isin][d] or 0)
                total += v
                invested += s["invested"]
                by_account[account] = round(by_account.get(account, 0) + v, 2)
            if d == days[-1]:
                total += cash
            rows.append((d, round(total, 2), round(invested, 2), round(total - invested, 2),
                         round((total - invested) / invested * 100, 2) if invested else 0.0,
                         json.dumps(by_account)))

        with db.connect() as conn:
            conn.execute("DELETE FROM portfolio_snapshots")
            conn.executemany("""
                INSERT INTO portfolio_snapshots (date, total_value, total_invested, pnl_eur, pnl_pct, by_account)
                VALUES (?, ?, ?, ?, ?, ?)""", rows)
            conn.commit()
        logger.info(f"Historique recalculé : {len(rows)} jours depuis {start}")
        return len(rows)


def schedule_rebuild(delay: float = 2.0):
    """Reconstruction en tâche de fond après une modification (regroupe les rafales)."""
    global _pending
    if _pending and not _pending.done():
        _pending.cancel()

    async def _run():
        await asyncio.sleep(delay)
        try:
            await rebuild()
        except Exception as e:
            logger.error(f"Reconstruction de l'historique : {e}")

    _pending = asyncio.get_event_loop().create_task(_run())


def get_history(range_key: str = "max") -> list[dict]:
    days = RANGES.get(range_key)
    sql, params = "SELECT date, total_value, total_invested, by_account FROM portfolio_snapshots", ()
    if days:
        sql += " WHERE date >= ?"
        params = ((date.today() - timedelta(days=days)).isoformat(),)
    with db.connect() as conn:
        out = db.rows(conn.execute(sql + " ORDER BY date", params))
    for r in out:
        r["by_account"] = json.loads(r["by_account"] or "{}")
    return out


def variation(days: int) -> dict | None:
    """Variation de la valeur, hors versements, sur N jours."""
    target = (date.today() - timedelta(days=days)).isoformat()
    with db.connect() as conn:
        past = conn.execute("SELECT * FROM portfolio_snapshots WHERE date <= ? ORDER BY date DESC LIMIT 1",
                            (target,)).fetchone()
        latest = conn.execute("SELECT * FROM portfolio_snapshots ORDER BY date DESC LIMIT 1").fetchone()
    if not past or not latest or not past["total_value"]:
        return None
    diff = (latest["total_value"] - latest["total_invested"]) - (past["total_value"] - past["total_invested"])
    return {"eur": round(diff, 2), "pct": round(diff / past["total_value"] * 100, 2)}
