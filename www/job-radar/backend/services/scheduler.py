"""
Boucles de fond (asyncio) — aucun cron hôte nécessaire.

Même forme que capital-control/services/scheduler.py : chaque boucle est un
`while True` dont le corps est protégé, de sorte qu'une erreur réseau ne tue
jamais la tâche.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings
import db
from services import actions, collector, notify

logger = logging.getLogger("jobs.scheduler")

TZ = ZoneInfo(settings.tz)
_tasks: list[asyncio.Task] = []

FIRST_RUN_DELAY = 20          # laisse l'app finir de démarrer
DAILY_HOUR = 6                # passe Adzuna quotidienne (heure locale)
ERROR_BACKOFF = 600


async def _sleep_until(hour: int, minute: int, weekday: int | None = None):
    now = datetime.now(TZ)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    while target <= now or (weekday is not None and target.weekday() != weekday):
        target += timedelta(days=1)
    await asyncio.sleep((target - now).total_seconds())


async def _collect_loop():
    """Sources sans contrainte de quota (FREQUENT_SOURCES)."""
    await asyncio.sleep(FIRST_RUN_DELAY)
    interval = max(1, settings.collect_hours) * 3600
    while True:
        try:
            await collector.run_sources(collector.FREQUENT_SOURCES)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:                                  # noqa: BLE001
            logger.error("Boucle de collecte : %s", e)
            await asyncio.sleep(ERROR_BACKOFF)


async def _daily_loop():
    """Adzuna : une seule passe par jour, quota Trial oblige (cf. collector)."""
    while True:
        try:
            await _sleep_until(DAILY_HOUR, 30)
            await collector.run_sources(collector.DAILY_SOURCES)
        except asyncio.CancelledError:
            raise
        except Exception as e:                                  # noqa: BLE001
            logger.error("Boucle quotidienne : %s", e)
            await asyncio.sleep(ERROR_BACKOFF)


def _heure_digest() -> tuple[int, int]:
    """Heure du récapitulatif, lue dans le profil (« HH:MM »)."""
    try:
        h, m = (db.get_profile().get("digest_hour") or "08:00").split(":")
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except Exception:                                       # noqa: BLE001
        return 8, 0


async def _digest_loop():
    """Un point par jour sur Discord : ce qui est arrivé, ce qui est à faire.

    Rien n'est envoyé s'il n'y a rien à dire — une notification quotidienne vide
    finit par être ignorée, et avec elle les vraies."""
    while True:
        try:
            h, m = _heure_digest()
            await _sleep_until(h, m)

            with db.connect() as conn:
                nouvelles = conn.execute(
                    "SELECT COUNT(*) c FROM offers o JOIN scores s ON s.offer_id=o.id "
                    "WHERE o.first_seen_at >= datetime('now', '-1 day') "
                    "AND s.match_score >= 55 AND COALESCE(s.lock_in_flag, 0) = 0"
                ).fetchone()["c"]
                a_trier = conn.execute(
                    "SELECT COUNT(*) c FROM offers o JOIN scores s ON s.offer_id=o.id "
                    "LEFT JOIN pipeline p ON p.offer_id=o.id "
                    "WHERE o.is_active=1 AND COALESCE(p.status,'nouveau')='nouveau' "
                    "AND s.match_score >= 40 AND COALESCE(s.lock_in_flag, 0) = 0"
                ).fetchone()["c"]

            champs = [{"name": g["label"], "value": str(len(g["items"])), "inline": True}
                      for g in actions.groups()]
            if nouvelles:
                champs.insert(0, {"name": "Nouvelles offres (24 h)",
                                  "value": str(nouvelles), "inline": True})

            if champs:
                await notify.send_embed(
                    "Le point du jour",
                    f"{a_trier} offre(s) en attente de tri.",
                    color="encre", fields=champs)
        except asyncio.CancelledError:
            raise
        except Exception as e:                              # noqa: BLE001
            logger.error("Boucle du récapitulatif : %s", e)
            await asyncio.sleep(ERROR_BACKOFF)


def start():
    loop = asyncio.get_event_loop()
    _tasks.append(loop.create_task(_collect_loop()))
    _tasks.append(loop.create_task(_daily_loop()))
    _tasks.append(loop.create_task(_digest_loop()))
    logger.info("Scheduler démarré (France Travail toutes les %d h, Adzuna à %dh30, "
                "récapitulatif quotidien)", settings.collect_hours, DAILY_HOUR)


def stop():
    for t in _tasks:
        t.cancel()
    _tasks.clear()
    logger.info("Scheduler arrêté")
