"""
Boucles de fond (asyncio) — aucun cron hôte nécessaire.

  - synchronisation bancaire à heures fixes (4 par jour : quota DSP2 sans l'utilisateur) ;
  - contrôle quotidien : consentement bancaire bientôt expiré, échecs de
    synchronisation répétés, solde bas.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import db
from config import settings
from services import notify, sync

logger = logging.getLogger("budget.scheduler")

TZ = ZoneInfo(settings.tz)
SYNC_HOURS = [(7, 0), (12, 0), (18, 0), (23, 0)]
CHECK_AT = (9, 0)
CONSENT_WARN_DAYS = 7
STARTUP_STALE_H = 6
ERROR_BACKOFF = 600
RETRY_AFTER = 900           # une passe en échec est retentée une fois, 15 min plus tard

_tasks: list[asyncio.Task] = []


def _next(times: list[tuple[int, int]]) -> datetime:
    now = datetime.now(TZ)
    cands = []
    for h, m in times:
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        cands.append(t if t > now else t + timedelta(days=1))
    return min(cands)


async def _sleep_until(times):
    await asyncio.sleep((_next(times) - datetime.now(TZ)).total_seconds())


async def _sync_loop():
    # Au démarrage : rattrapage seulement si la dernière passe est ancienne.
    await asyncio.sleep(15)
    try:
        last = (db.get_json("sync_state", {}) or {}).get("last_ok")
        if not last or datetime.now(TZ) - datetime.fromisoformat(last) > timedelta(hours=STARTUP_STALE_H):
            await sync.run()
    except Exception as e:                                      # noqa: BLE001
        logger.error("Rattrapage de synchronisation : %s", e)
    while True:
        try:
            await _sleep_until(SYNC_HOURS)
            if not (await sync.run())["ok"]:
                await asyncio.sleep(RETRY_AFTER)
                await sync.run()
        except asyncio.CancelledError:
            raise
        except Exception as e:                                  # noqa: BLE001
            logger.error("Boucle de synchronisation : %s", e)
            await asyncio.sleep(ERROR_BACKOFF)


async def daily_check():
    sess = db.get_json("eb_session")
    if sess and sess.get("valid_until"):
        left = (datetime.fromisoformat(sess["valid_until"].replace("Z", "+00:00"))
                - datetime.now(TZ)).days
        if left < 0:
            await notify.once_a_day("consent", "Banque déconnectée",
                                    "L'accès à la banque a expiré. Reconnecte-la depuis "
                                    "Budget › Réglages.", "red")
        elif left <= CONSENT_WARN_DAYS:
            await notify.once_a_day("consent", "Accès bancaire à renouveler",
                                    f"Il expire dans {left} jour(s). Budget › Réglages › Renouveler.")

    st = db.get_json("sync_state", {}) or {}
    last_ok = st.get("last_ok")
    if last_ok and datetime.now(TZ) - datetime.fromisoformat(last_ok) > timedelta(hours=48):
        await notify.once_a_day("sync_stale", "Synchronisation bancaire à l'arrêt",
                                "Aucune synchronisation réussie depuis plus de 48 h.", "red")
    if st.get("fails", 0) >= 2:
        await notify.once_a_day("sync", "Synchronisation bancaire en échec",
                                f"{st['fails']} échecs de suite. Dernière erreur : {st.get('last_error')}", "red")

    low = float(db.get_settings().get("low_balance") or 0)
    if low > 0:
        with db.connect() as c:
            bal = c.execute("SELECT SUM(balance) FROM accounts WHERE active = 1 AND balance IS NOT NULL").fetchone()[0]
        if bal is not None and bal < low:
            await notify.once_a_day("low", "Solde bas",
                                    f"Solde : {bal:,.2f} € (seuil {low:,.0f} €).".replace(",", " "), "yellow")


async def _check_loop():
    while True:
        try:
            await _sleep_until([CHECK_AT])
            await daily_check()
        except asyncio.CancelledError:
            raise
        except Exception as e:                                  # noqa: BLE001
            logger.error("Contrôle quotidien : %s", e)
            await asyncio.sleep(ERROR_BACKOFF)


def start():
    _tasks.extend([asyncio.create_task(_sync_loop()), asyncio.create_task(_check_loop())])


def stop():
    for t in _tasks:
        t.cancel()
    _tasks.clear()
