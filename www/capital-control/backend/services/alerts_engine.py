"""
Moteur d'alertes — évalue les règles après chaque cycle de prix :
prix au-dessus / en dessous d'un seuil, variation du jour au-delà de ±N %.
"""
import logging
from datetime import datetime, timedelta

import db
from services.discord import send_embed

logger = logging.getLogger("capital.alerts")

KIND_LABELS = {
    "price_above": "Prix au-dessus de",
    "price_below": "Prix en-dessous de",
    "pct_day": "Variation jour ≥",
}


def _cooldown_ok(rule: dict) -> bool:
    if not rule.get("last_fired"):
        return True
    try:
        last = datetime.fromisoformat(rule["last_fired"])
    except ValueError:
        return True
    return datetime.now() - last > timedelta(hours=rule.get("cooldown_h") or 24)


async def evaluate():
    """Passe sur toutes les règles actives. Déclenche → alert_events + Discord."""
    with db.connect() as conn:
        rules = db.rows(conn.execute("SELECT * FROM alert_rules WHERE enabled = 1"))
    if not rules:
        return

    prices = db.get_prices()
    assets = {a["isin"]: a for a in db.get_all_assets()}

    for rule in rules:
        if not _cooldown_ok(rule):
            continue
        isin = rule.get("isin")
        asset = assets.get(isin, {})
        name = asset.get("name", isin or "?")
        quote = prices.get(isin, {})
        kind, threshold = rule["kind"], rule["threshold"]
        fired, detail = False, ""

        if kind in ("price_above", "price_below"):
            price = quote.get("price_eur")
            if price is None:
                continue
            if kind == "price_above" and price >= threshold:
                fired, detail = True, f"{name} : {price:.2f}€ ≥ seuil {threshold:.2f}€"
            elif kind == "price_below" and price <= threshold:
                fired, detail = True, f"{name} : {price:.2f}€ ≤ seuil {threshold:.2f}€"

        elif kind == "pct_day":
            chg = quote.get("change_24h")
            if chg is None:
                continue
            if abs(chg) >= threshold:
                fired = True
                detail = f"{name} : {chg:+.2f}% sur 24h (seuil ±{threshold:.1f}%)"

        if fired:
            now = datetime.now().isoformat()
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO alert_events (rule_id, isin, message) VALUES (?, ?, ?)",
                    (rule["id"], isin, detail))
                conn.execute("UPDATE alert_rules SET last_fired = ? WHERE id = ?",
                             (now, rule["id"]))
                conn.commit()
            logger.info(f"Alerte déclenchée : {detail}")
            await send_embed(f"🔔 Alerte — {KIND_LABELS.get(kind, kind)} {threshold:g}",
                             detail, color="yellow")
