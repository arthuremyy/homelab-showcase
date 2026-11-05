"""Provider: taux de change via Yahoo Finance (USDEUR=X, GBPEUR=X, ...)."""
import logging
from datetime import datetime

import db
from providers.stocks import get_stock_price

logger = logging.getLogger("capital.fx")


async def refresh_fx(currencies: set[str]):
    """Met à jour fx_rates pour chaque devise ≠ EUR (paire {CUR}EUR)."""
    for cur in currencies:
        if not cur or cur.upper() == "EUR":
            continue
        pair = f"{cur.upper()}EUR"
        quote = await get_stock_price(f"{cur.upper()}EUR=X")
        if quote and quote.get("price"):
            with db.connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO fx_rates (pair, rate, updated_at) VALUES (?, ?, ?)",
                    (pair, quote["price"], datetime.now().isoformat()))
                conn.commit()


def to_eur(amount: float, currency: str) -> float | None:
    """Convertit vers EUR via fx_rates. None si taux inconnu."""
    if not currency or currency.upper() == "EUR":
        return amount
    with db.connect() as conn:
        r = conn.execute("SELECT rate FROM fx_rates WHERE pair = ?",
                         (f"{currency.upper()}EUR",)).fetchone()
    return amount * r["rate"] if r and r["rate"] else None
