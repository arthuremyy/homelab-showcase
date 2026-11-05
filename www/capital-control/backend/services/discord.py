"""Notifications Discord — embeds vers #new-financing (DISCORD_WEBHOOK_FINANCE)."""
import logging

import httpx

from config import settings

logger = logging.getLogger("capital.discord")

COLORS = {"green": 0x10B981, "red": 0xEF4444, "yellow": 0xF59E0B, "blue": 0x3B82F6}


async def send_embed(title: str, description: str, color: str = "blue",
                     fields: list[dict] | None = None) -> bool:
    """POST webhook Discord. Échec silencieux (loggé) — ne bloque jamais l'appelant."""
    if not settings.discord_webhook:
        logger.debug("DISCORD_WEBHOOK_FINANCE absent — notification ignorée")
        return False
    embed = {
        "title": title[:256],
        "description": description[:4000],
        "color": COLORS.get(color, COLORS["blue"]),
    }
    if fields:
        embed["fields"] = [{"name": f["name"][:256], "value": str(f["value"])[:1024],
                            "inline": f.get("inline", True)} for f in fields[:12]]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.discord_webhook,
                                     json={"username": "Capital Control", "embeds": [embed]})
            return resp.status_code < 300
    except Exception as e:
        logger.warning(f"Discord webhook error: {e}")
        return False
