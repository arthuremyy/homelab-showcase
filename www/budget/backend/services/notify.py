"""Notifications Discord — embeds vers #new-financing (DISCORD_WEBHOOK_FINANCE).

Même client que capital-control/services/discord.py. Chaque alerte est
dédoublonnée par jour (meta `notified`) : une alerte répétée finit ignorée.
"""
import logging
from datetime import date

import httpx

import db
from config import settings

logger = logging.getLogger("budget.notify")

COLORS = {"green": 0x10B981, "red": 0xEF4444, "yellow": 0xF59E0B, "blue": 0x3B82F6}


async def send_embed(title: str, description: str, color: str = "blue") -> bool:
    if not settings.discord_webhook:
        logger.debug("DISCORD_WEBHOOK_FINANCE absent — notification ignorée")
        return False
    embed = {"title": title[:256], "description": description[:4000],
             "color": COLORS.get(color, COLORS["blue"])}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.discord_webhook,
                                     json={"username": "Budget", "embeds": [embed]})
            if resp.status_code >= 300:
                logger.warning("Discord : HTTP %s", resp.status_code)
            return resp.status_code < 300
    except Exception as e:                                      # noqa: BLE001
        logger.warning("Discord : %s", e)
        return False


async def once_a_day(key: str, title: str, description: str, color: str = "yellow") -> bool:
    sent = db.get_json("notified", {}) or {}
    today = date.today().isoformat()
    if sent.get(key) == today:
        return False
    ok = await send_embed(title, description, color)
    if ok:
        sent[key] = today
        db.set_json("notified", {k: v for k, v in sent.items() if v >= today[:7]})
    return ok
