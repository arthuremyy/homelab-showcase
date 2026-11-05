"""
Pointage — compare ce qu'affiche l'établissement (quantités, valeurs) au calcul à la même date.

Écart de quantité → un mouvement manque : on propose un rattrapage (achat ou vente au prix du jour,
source « pointage », modifiable ensuite). Écart de prix → la source de cours diverge : on le signale,
on ne corrige rien. Chaque pointage est conservé (table checks).
"""
import json
from datetime import date

import db
from services import valuation

# Tolérances : quantité (arrondi d'affichage) et prix (cours de clôture vs temps réel, spread crypto).
SHARE_TOL = {"crypto": 1e-6}
SHARE_TOL_DEFAULT = 1e-4
PRICE_TOL_PCT = {"crypto": 2.0, "monetary": 0.5}
PRICE_TOL_PCT_DEFAULT = 1.5


def _holdings(account: str, as_of: str) -> dict[str, dict]:
    txs = db.get_transactions(account)
    return {isin: valuation.replay(group, as_of)
            for (isin, _), group in valuation.group_transactions(txs).items()}


def evaluate(account: str, as_of: str, declared: list[dict], cash: float | None = None,
             prices: dict[str, float] | None = None) -> dict:
    """declared : [{isin, shares, value?, price?, lots?}] ; prices : prix de référence à la date
    (défaut : derniers prix connus). Toute ligne détenue mais non déclarée compte comme 0."""
    assets = {a["isin"]: a for a in db.get_all_assets()}
    last = {i: q.get("price_eur") for i, q in db.get_prices().items()}
    ref = {**last, **(prices or {})}
    held = _holdings(account, as_of)
    by_isin = {d["isin"]: d for d in declared}
    isins = [i for i, s in held.items() if s["shares"] > 0] + [i for i in by_isin if i not in held
                                                                or not held[i]["shares"]]
    lines, ok = [], True
    for isin in dict.fromkeys(isins):
        a = assets.get(isin, {})
        cls = a.get("asset_class") or a.get("asset_type") or ""
        comp = held.get(isin, {"shares": 0.0, "lots": {}})
        d = by_isin.get(isin, {"shares": 0.0})
        dec_shares = float(d.get("shares") or 0)
        dec_price = d.get("price") or ((d["value"] / dec_shares) if d.get("value") and dec_shares else None)
        our_price = ref.get(isin)
        share_gap = round(dec_shares - comp["shares"], 8)
        share_ok = abs(share_gap) <= SHARE_TOL.get(cls, SHARE_TOL_DEFAULT)
        price_gap = (round((our_price - dec_price) / dec_price * 100, 2)
                     if dec_price and our_price else None)
        price_ok = price_gap is None or abs(price_gap) <= PRICE_TOL_PCT.get(cls, PRICE_TOL_PCT_DEFAULT)
        line = {
            "isin": isin, "name": a.get("name") or isin,
            "declared_shares": dec_shares, "computed_shares": round(comp["shares"], 8),
            "share_gap": share_gap, "share_ok": share_ok,
            "declared_price": dec_price, "our_price": our_price,
            "price_gap_pct": price_gap, "price_ok": price_ok,
            "declared_value": round(d["value"], 2) if d.get("value") else
                              (round(dec_shares * dec_price, 2) if dec_price else None),
            "computed_value": round(comp["shares"] * (our_price or 0), 2),
        }
        if d.get("lots") is not None:                  # PEE : contrôle par date de disponibilité
            comp_lots = {k or None: v for k, v in comp["lots"].items()}
            line["lots"] = [{"available_on": k, "declared_shares": d["lots"].get(k, 0.0),
                             "computed_shares": round(comp_lots.get(k, 0.0), 6),
                             "ok": abs(d["lots"].get(k, 0.0) - comp_lots.get(k, 0.0)) <= SHARE_TOL_DEFAULT}
                            for k in sorted(set(d["lots"]) | set(comp_lots), key=lambda x: x or "")]
        ok = ok and share_ok and price_ok
        lines.append(line)

    declared_total = sum(l["declared_value"] or l["computed_value"] for l in lines) + (cash or 0)
    computed_total = sum(l["computed_value"] for l in lines) + (cash or 0)
    return {"account": account, "date": as_of, "status": "ok" if ok else "ecart",
            "declared_total": round(declared_total, 2), "computed_total": round(computed_total, 2),
            "cash": cash, "lines": lines,
            "share_gaps": sum(1 for l in lines if not l["share_ok"]),
            "price_gaps": sum(1 for l in lines if not l["price_ok"])}


def commit(result: dict, adjust: bool, source: str = "manuel") -> dict:
    """Enregistre le pointage ; avec `adjust`, crée les mouvements de rattrapage des quantités."""
    account, as_of = result["account"], result["date"]
    created = 0
    with db.connect() as conn:
        if adjust:
            assets = {a["isin"]: a for a in db.get_all_assets()}
            provider = conn.execute("SELECT provider FROM accounts WHERE id = ?", (account,)).fetchone()[0]
            note = f"Pointage du {date.fromisoformat(as_of):%d/%m/%Y} — date et prix à préciser"
            for l in result["lines"]:
                if l["share_ok"]:
                    continue
                price = l["declared_price"] or l["our_price"] or 0
                # PEE : un mouvement par date de disponibilité en écart ; sinon un seul.
                gaps = ([(x["declared_shares"] - x["computed_shares"], x["available_on"])
                         for x in l["lots"] if not x["ok"]] if l.get("lots") else [(l["share_gap"], None)])
                for gap, available_on in gaps:
                    qty = round(abs(gap), 8)
                    conn.execute("""
                        INSERT INTO transactions (date, type, isin, name, shares, price, amount, fees,
                                                  account, broker, note, source, available_on)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 'pointage', ?)
                    """, (as_of, "buy" if gap > 0 else "sell", l["isin"],
                          assets.get(l["isin"], {}).get("name", l["name"]), qty, price,
                          round(qty * price, 2), account, provider, note, available_on))
                    created += 1
                l["share_ok"], l["computed_shares"] = True, l["declared_shares"]
                l["computed_value"] = round(l["declared_shares"] * (l["our_price"] or 0), 2)
            result["computed_total"] = round(sum(l["computed_value"] for l in result["lines"])
                                             + (result.get("cash") or 0), 2)
            if all(l["share_ok"] and l["price_ok"] for l in result["lines"]):
                result["status"] = "ok"
        if result.get("cash") is not None and as_of == date.today().isoformat():
            conn.execute("UPDATE accounts SET cash = ? WHERE id = ?", (result["cash"], account))
        cur = conn.execute("""
            INSERT INTO checks (account, date, source, declared_total, computed_total, status, lines, adjustments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (account, as_of, source, result["declared_total"], result["computed_total"],
              result["status"], json.dumps(result["lines"], ensure_ascii=False), created))
        conn.commit()
    return {"id": cur.lastrowid, "status": result["status"], "adjustments": created}
