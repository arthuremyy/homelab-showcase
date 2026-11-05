"""
Pricing — met à jour prices_last pour tous les actifs du registre.
Crypto via CoinGecko, actions/ETF via Yahoo, conversion EUR via fx_rates.
"""
import logging
from datetime import datetime

import db
from providers.market_data import get_crypto_prices
from providers.stocks import get_all_stock_prices
from providers.fx import refresh_fx, to_eur

logger = logging.getLogger("capital.pricing")


async def update_all_prices(include_stocks: bool = True) -> int:
    """Rafraîchit les prix. Retourne le nombre d'actifs mis à jour."""
    assets = db.get_all_assets()
    if not assets:
        return 0

    crypto_assets = [a for a in assets if a["asset_type"] == "crypto" and a.get("coingecko_id")]
    stock_assets = [a for a in assets if a["asset_type"] in ("stock", "etf") and a.get("ticker")]

    updated = 0
    now = datetime.now().isoformat()

    if crypto_assets:
        try:
            data = await get_crypto_prices([a["coingecko_id"] for a in crypto_assets], "eur")
            with db.connect() as conn:
                for a in crypto_assets:
                    q = data.get(a["coingecko_id"], {})
                    if q.get("eur"):
                        conn.execute("""
                            INSERT OR REPLACE INTO prices_last
                                (isin, price, currency, price_eur, change_24h, updated_at)
                            VALUES (?, ?, 'EUR', ?, ?, ?)
                        """, (a["isin"], q["eur"], q["eur"], q.get("eur_24h_change", 0), now))
                        updated += 1
                conn.commit()
        except Exception as e:
            logger.error(f"Crypto price update error: {e}")

    if include_stocks and stock_assets:
        try:
            data = await get_all_stock_prices([a["ticker"] for a in stock_assets])
            # Devises présentes → rafraîchir FX avant conversion
            currencies = {q.get("currency", "EUR") for q in data.values()} - {"EUR", None}
            if currencies:
                await refresh_fx(currencies)
            with db.connect() as conn:
                for a in stock_assets:
                    q = data.get(a["ticker"])
                    if not q or not q.get("price"):
                        continue
                    currency = q.get("currency", "EUR")
                    price_eur = to_eur(q["price"], currency)
                    if price_eur is None:
                        logger.warning(f"Pas de taux {currency}EUR — {a['ticker']} ignoré")
                        continue
                    prev = q.get("previous_close") or 0
                    chg = ((q["price"] - prev) / prev * 100) if prev else 0
                    conn.execute("""
                        INSERT OR REPLACE INTO prices_last
                            (isin, price, currency, price_eur, change_24h, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (a["isin"], q["price"], currency, round(price_eur, 6),
                          round(chg, 4), now))
                    updated += 1
                conn.commit()
        except Exception as e:
            logger.error(f"Stock price update error: {e}")

    return updated
