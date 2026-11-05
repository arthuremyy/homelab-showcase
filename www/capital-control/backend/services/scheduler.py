"""
Scheduler — boucles asyncio lancées au démarrage (lifespan).
  prices   : crypto 90 s en continu ; actions 5 min aux heures de marché, 1 h sinon
  history  : historique recalculé au démarrage + chaque jour à 23h50
  briefing : chaque semaine (BRIEFING_DAY à BRIEFING_HOUR, si pas déjà généré) + résumé Discord
  weekly   : dimanche 19h — récap hebdo Discord, avec les comptes à pointer
Chaque boucle est blindée : une erreur est loggée, jamais fatale.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import db
from config import settings
from services import history, pricing, valuation
from services.alerts_engine import evaluate as evaluate_alerts
from services.discord import send_embed

logger = logging.getLogger("capital.scheduler")

TZ = ZoneInfo(settings.tz)

CRYPTO_INTERVAL = 90
STOCK_INTERVAL_OPEN = 300
STOCK_INTERVAL_CLOSED = 3600

_tasks: list[asyncio.Task] = []
_last_stock_update = 0.0


def market_open(now: datetime | None = None) -> bool:
    """Euronext Paris approx : lun-ven 09:00–17:45 (heure de Paris)."""
    now = now or datetime.now(TZ)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 17 * 60 + 45


async def _price_loop():
    global _last_stock_update
    while True:
        try:
            loop_t = asyncio.get_event_loop().time()
            interval = STOCK_INTERVAL_OPEN if market_open() else STOCK_INTERVAL_CLOSED
            include_stocks = (loop_t - _last_stock_update) >= interval
            await pricing.update_all_prices(include_stocks=include_stocks)
            if include_stocks:
                _last_stock_update = loop_t
            await evaluate_alerts()
        except Exception as e:
            logger.error(f"price loop error: {e}")
        await asyncio.sleep(CRYPTO_INTERVAL)


async def _sleep_until(hour: int, minute: int, weekday: int | None = None):
    """Dort jusqu'à la prochaine occurrence de HH:MM (optionnellement un jour précis, 0=lundi)."""
    now = datetime.now(TZ)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    while target <= now or (weekday is not None and target.weekday() != weekday):
        target += timedelta(days=1)
    await asyncio.sleep((target - now).total_seconds())


async def _history_loop():
    await asyncio.sleep(20)          # laisser passer la première mise à jour des prix
    while True:
        try:
            await history.rebuild()
        except Exception as e:
            logger.error(f"history rebuild error: {e}")
        await _sleep_until(23, 50)


async def _briefing_loop():
    try:
        h, m = (int(x) for x in settings.briefing_hour.split(":"))
    except ValueError:
        h, m = 7, 30
    weekday = settings.briefing_day
    while True:
        try:
            await _sleep_until(h, m, weekday=weekday)
            today = datetime.now(TZ).strftime("%d/%m/%Y")
            with db.connect() as conn:
                exists = conn.execute("SELECT 1 FROM briefings WHERE date = ?", (today,)).fetchone()
            if exists:
                continue
            from routers.briefing import generate_and_store   # import tardif (cycle)
            result = await generate_and_store()
            if result.get("status") == "ok":
                b = result["briefing"]
                sentiment = {"bullish": "🟢 Haussier", "bearish": "🔴 Baissier",
                             "neutral": "🟡 Neutre"}.get(b.get("market_sentiment"),
                                                         b.get("market_sentiment", "?"))
                fields = [{"name": "Sentiment",
                           "value": f"{sentiment} ({b.get('sentiment_score', '?')})"}]
                summary = valuation.portfolio_summary()
                fields.append({"name": "Portefeuille",
                               "value": f"{summary['total_value']:.2f}€ "
                                        f"({summary['day_change_eur']:+.2f}€ jour)"})
                if b.get("focus_du_jour"):
                    fields.append({"name": "🎯 Focus", "value": b["focus_du_jour"],
                                   "inline": False})
                if b.get("conseil_du_jour"):
                    fields.append({"name": "💡 Conseil", "value": b["conseil_du_jour"],
                                   "inline": False})
                await send_embed("Briefing hebdomadaire — Capital",
                                 b.get("summary", ""),
                                 color="blue", fields=fields)
            else:
                logger.error(f"briefing auto: {result.get('error')}")
        except Exception as e:
            logger.error(f"briefing loop error: {e}")
            await asyncio.sleep(600)


async def _weekly_loop():
    while True:
        try:
            await _sleep_until(19, 0, weekday=6)   # dimanche
            summary = valuation.portfolio_summary()
            week = history.variation(7)
            fields = [
                {"name": "Valeur", "value": f"{summary['total_value']:.2f}€"},
                {"name": "Gain", "value": f"{summary['pnl_eur']:+.2f}€ ({summary['pnl_pct']:+.2f}%)"},
            ]
            if week:
                fields.append({"name": "Semaine", "value": f"{week['eur']:+.2f}€ ({week['pct']:+.2f}%)"})
            labels = {"a_pointer": "à pointer", "ecart": "écart non résolu"}
            todo = [f"• {a['name']} : {labels[a['check']['state']]}"
                    + (f" (dernier pointage il y a {a['check']['age_days']} j)" if a["check"]["date"] else "")
                    for a in summary["accounts"] if a["check"]["state"] != "ok"]
            desc = "\n".join(f"• {a['name']} : {a['value']:.2f}€ ({a['pnl_eur']:+.2f}€)"
                             for a in summary["accounts"])
            if todo:
                desc += "\n\n**Pointage**\n" + "\n".join(todo) + "\nhttps://capital.example.com/"
            await send_embed("Récap hebdo — Capital", desc, color="yellow" if todo else "blue", fields=fields)
        except Exception as e:
            logger.error(f"weekly loop error: {e}")
            await asyncio.sleep(600)


def start():
    loop = asyncio.get_event_loop()
    for coro in (_price_loop(), _history_loop(), _briefing_loop(), _weekly_loop()):
        _tasks.append(loop.create_task(coro))
    logger.info("Scheduler démarré (prix, historique, briefing, hebdo)")


def stop():
    for t in _tasks:
        t.cancel()
    _tasks.clear()
