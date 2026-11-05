"""
Notifications Discord.

Le webhook est lu depuis le PROFIL avant l'environnement : c'est déjà la forme
multi-utilisateur (chaque compte aura le sien), et ça permet de le changer sans
redéployer. L'échec est silencieux et loggé — une notification ratée ne doit
jamais interrompre une collecte.
"""
import logging

import httpx

import db
from config import settings

logger = logging.getLogger("jobs.notify")

COLORS = {"vert": 0x4A6B4F, "sienne": 0x9A4F2E, "encre": 0x1A1815, "rouge": 0x8C3A2E}


def webhook() -> str:
    try:
        perso = (db.get_profile().get("discord_webhook") or "").strip()
    except Exception:                                    # base non initialisée
        perso = ""
    return perso or settings.discord_webhook


async def send_embed(title: str, description: str = "", color: str = "encre",
                     fields: list[dict] | None = None, url: str | None = None) -> bool:
    hook = webhook()
    if not hook:
        logger.debug("Aucun webhook configuré — notification ignorée")
        return False
    embed = {
        "title": title[:256],
        "description": description[:4000],
        "color": COLORS.get(color, COLORS["encre"]),
    }
    if url:
        embed["url"] = url
    if fields:
        embed["fields"] = [{"name": f["name"][:256], "value": str(f["value"])[:1024],
                            "inline": f.get("inline", False)} for f in fields[:12]]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(hook, json={"username": "Job Radar", "embeds": [embed]})
            return r.status_code < 300
    except Exception as e:                               # noqa: BLE001
        logger.warning("Webhook Discord : %s", e)
        return False
