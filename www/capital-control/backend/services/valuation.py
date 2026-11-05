"""
Valorisation — positions dérivées des transactions (source de vérité), par (actif, compte).

Trois montants par position :
  invested  = argent versé par moi (achats + frais)
  employer  = abondement net de prélèvements sociaux (PEE) — un gain, pas un versement
  cost      = base de coût des parts (invested + employer) → PRU
Gain = valeur − versé ; plus-value de marché = valeur − coût.
"""
from datetime import date

import db

PEA_PLAFOND = 150000.0
# Au-delà, un compte est « à pointer ». Le PEE ne bouge qu'aux versements (chacun produit un avis).
CHECK_MAX_AGE_DAYS = {"PEE": 92}
CHECK_MAX_AGE_DEFAULT = 31


def replay(txs: list[dict], as_of: str | None = None) -> dict:
    """Rejoue les transactions d'un groupe (isin, compte) en ordre chronologique.

    buy  : parts += shares ; versé += amount + fees ; abondement += employer − prélèvements
    sell : retire versé, abondement et coût au prorata, dégage le P&L réalisé ;
           les lots (date de disponibilité) sont consommés du plus ancien au plus récent
    """
    shares = invested = employer = cost = realized = dividends = fees_total = 0.0
    lots: dict[str, float] = {}

    for tx in sorted(txs, key=lambda t: (t["date"], t["id"])):
        if as_of and tx["date"] > as_of:
            break
        t = tx["type"]
        fees = abs(tx.get("fees") or 0)
        if t == "buy":
            own = abs(tx["amount"]) + fees
            emp = abs(tx.get("employer_amount") or 0) - abs(tx.get("social_tax") or 0)
            invested += own
            employer += emp
            cost += own + emp
            shares += abs(tx["shares"])
            key = tx.get("available_on") or ""
            lots[key] = lots.get(key, 0.0) + abs(tx["shares"])
            fees_total += fees
        elif t == "sell" and shares > 0:
            qty = min(abs(tx["shares"]), shares)
            ratio = qty / shares
            realized += abs(tx["amount"]) - fees - cost * ratio
            invested -= invested * ratio
            employer -= employer * ratio
            cost -= cost * ratio
            shares -= qty
            fees_total += fees
            for key in sorted(lots):
                take = min(lots[key], qty)
                lots[key] -= take
                qty -= take
                if qty <= 1e-12:
                    break
        elif t == "dividend":
            dividends += abs(tx["amount"])
        elif t == "fee":
            fees_total += abs(tx["amount"])

    if shares < 1e-9:
        shares = invested = employer = cost = 0.0
    return {
        "shares": shares, "invested": invested, "employer": employer, "cost": cost,
        "realized_pnl": realized, "dividends": dividends, "fees_total": fees_total,
        "lots": {k: v for k, v in lots.items() if v > 1e-9},
    }


def group_transactions(txs: list[dict]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    for tx in txs:
        if tx.get("isin"):
            groups.setdefault((tx["isin"], tx["account"]), []).append(tx)
    return groups


def compute_positions(as_of: str | None = None) -> list[dict]:
    """Positions (ouvertes et soldées) valorisées aux derniers prix connus."""
    assets = {a["isin"]: a for a in db.get_all_assets()}
    prices = db.get_prices()
    positions = []
    for (isin, account), group in group_transactions(db.get_transactions()).items():
        s = replay(group, as_of)
        asset = assets.get(isin, {})
        quote = prices.get(isin, {})
        price = quote.get("price_eur") or 0.0
        value = s["shares"] * price
        chg = quote.get("change_24h") or 0.0
        day_pnl = value - value / (1 + chg / 100) if -100 < chg != 0 else 0.0
        positions.append({
            "isin": isin,
            "name": asset.get("name") or group[0].get("name") or isin,
            "account": account,
            "asset_type": asset.get("asset_type", "stock"),
            "asset_class": asset.get("asset_class"),
            "ticker": asset.get("ticker") or "",
            "coingecko_id": asset.get("coingecko_id") or "",
            "shares": round(s["shares"], 8),
            "pru": round(s["cost"] / s["shares"], 4) if s["shares"] else 0.0,
            "invested": round(s["invested"], 2),
            "employer": round(s["employer"], 2),
            "cost": round(s["cost"], 2),
            "price_eur": price,
            "change_24h": round(chg, 2),
            "price_updated_at": quote.get("updated_at"),
            "value": round(value, 2),
            "pnl_eur": round(value - s["invested"], 2),
            "pnl_pct": round((value - s["invested"]) / s["invested"] * 100, 2) if s["invested"] else 0.0,
            "market_pnl": round(value - s["cost"], 2),
            "day_pnl_eur": round(day_pnl, 2),
            "realized_pnl": round(s["realized_pnl"], 2),
            "dividends": round(s["dividends"], 2),
            "lots": [{"available_on": k or None, "shares": round(v, 6), "value": round(v * price, 2)}
                     for k, v in sorted(s["lots"].items())],
            "closed": s["shares"] == 0,
        })
    total_value = sum(p["value"] for p in positions)
    for p in positions:
        p["weight_pct"] = round(p["value"] / total_value * 100, 1) if total_value else 0.0
    return sorted(positions, key=lambda p: -p["value"])


def _last_checks() -> dict[str, dict]:
    with db.connect() as conn:
        rows = db.rows(conn.execute("""
            SELECT c.* FROM checks c
            JOIN (SELECT account, MAX(id) id FROM checks GROUP BY account) m ON m.id = c.id
        """))
    return {r["account"]: r for r in rows}


def check_state(account: str, last: dict | None) -> dict:
    """État de pointage d'un compte : ok | a_pointer | ecart."""
    max_age = CHECK_MAX_AGE_DAYS.get(account, CHECK_MAX_AGE_DEFAULT)
    if not last:
        return {"state": "a_pointer", "date": None, "age_days": None, "max_age": max_age}
    age = (date.today() - date.fromisoformat(last["date"])).days
    if last["status"] == "ecart":
        state = "ecart"
    elif age > max_age:
        state = "a_pointer"
    else:
        state = "ok"
    return {"state": state, "date": last["date"], "age_days": age, "max_age": max_age,
            "declared_total": last["declared_total"], "computed_total": last["computed_total"]}


def _sum(items, key):
    return round(sum(p[key] for p in items), 2)


def portfolio_summary() -> dict:
    positions = compute_positions()
    open_pos = [p for p in positions if not p["closed"]]
    checks = _last_checks()

    accounts = []
    for acc in db.get_accounts():
        mine = [p for p in open_pos if p["account"] == acc["id"]]
        value = _sum(mine, "value") + (acc["cash"] or 0)
        invested = _sum(mine, "invested")
        accounts.append({
            **acc,
            "value": round(value, 2),
            "invested": invested,
            "employer": _sum(mine, "employer"),
            "pnl_eur": round(value - invested, 2),
            "pnl_pct": round((value - invested) / invested * 100, 2) if invested else 0.0,
            "day_pnl_eur": _sum(mine, "day_pnl_eur"),
            "position_count": len(mine),
            "check": check_state(acc["id"], checks.get(acc["id"])),
            "oldest_quote_at": min((p["price_updated_at"] for p in mine if p["price_updated_at"]),
                                   default=None),
        })

    total_value = round(sum(a["value"] for a in accounts), 2)
    invested = round(sum(a["invested"] for a in accounts), 2)
    day = _sum(open_pos, "day_pnl_eur")
    by_class: dict[str, float] = {}
    for p in open_pos:
        by_class[p["asset_class"] or "autre"] = by_class.get(p["asset_class"] or "autre", 0) + p["value"]

    return {
        "total_value": total_value,
        "total_invested": invested,
        "employer": round(sum(a["employer"] for a in accounts), 2),
        "pnl_eur": round(total_value - invested, 2),
        "pnl_pct": round((total_value - invested) / invested * 100, 2) if invested else 0.0,
        "realized_pnl": _sum(positions, "realized_pnl"),
        "dividends": _sum(positions, "dividends"),
        "day_change_eur": day,
        "day_change_pct": round(day / (total_value - day) * 100, 2) if total_value - day > 0 else 0.0,
        "position_count": len(open_pos),
        "by_account": {a["id"]: {"value": a["value"], "invested": a["invested"]} for a in accounts},
        "by_class": [{"label": k, "value": round(v, 2),
                      "pct": round(v / total_value * 100, 1) if total_value else 0.0}
                     for k, v in sorted(by_class.items(), key=lambda x: -x[1])],
        "accounts": accounts,
        "oldest_quote_at": min((p["price_updated_at"] for p in open_pos if p["price_updated_at"]),
                               default=None),
        "positions": positions,
    }


def pea_status() -> dict:
    """Plafond PEA : approché par les sommes versées pour les achats (frais compris)."""
    versements = sum(abs(t["amount"]) + abs(t.get("fees") or 0)
                     for t in db.get_transactions("PEA") if t["type"] == "buy")
    return {
        "versements": round(versements, 2),
        "plafond": PEA_PLAFOND,
        "restant": round(PEA_PLAFOND - versements, 2),
        "utilisation_pct": round(versements / PEA_PLAFOND * 100, 2),
    }
