"""Tests sans réseau : valorisation (PEE, lots), lecture d'un avis Natixis, pointage.
Base SQLite temporaire ; chiffres fictifs.

    python3 test_capital.py
"""
import os
import sys
import tempfile

os.environ.setdefault("JWT_SECRET", "test")
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

import db                                                   # noqa: E402
from services import checks, natixis, valuation             # noqa: E402

fails = 0


def check(ok, msg):
    global fails
    print(("  ✅ " if ok else "  ❌ ÉCHEC ") + msg)
    fails += 0 if ok else 1


def tx(i, d, t, shares, price, amount, **kw):
    return {"id": i, "date": d, "type": t, "shares": shares, "price": price, "amount": amount, **kw}


print("--- valorisation ---")
s = valuation.replay([
    tx(1, "2025-04-01", "buy", 10, 20, 180, employer_amount=30, social_tax=10, available_on="2030-09-01"),
    tx(2, "2026-04-01", "buy", 5, 22, 110, available_on="2031-09-01"),
])
check(abs(s["invested"] - 290) < 1e-9, "versé = montants personnels")
check(abs(s["employer"] - 20) < 1e-9, "abondement net de prélèvements sociaux")
check(abs(s["cost"] - 310) < 1e-9, "coût = versé + abondement net")
check(s["lots"] == {"2030-09-01": 10, "2031-09-01": 5}, "lots par date de disponibilité")
s = valuation.replay([
    tx(1, "2025-04-01", "buy", 10, 20, 200, available_on="2030-09-01"),
    tx(2, "2026-04-01", "buy", 10, 30, 300, available_on="2031-09-01"),
    tx(3, "2026-05-01", "sell", 15, 40, 600),
])
check(s["lots"] == {"2031-09-01": 5}, "une vente consomme les lots les plus anciens")
check(abs(s["realized_pnl"] - (600 - 375)) < 1e-9, "P&L réalisé au coût moyen")
check(valuation.replay([tx(1, "2026-01-01", "buy", 1, 10, 10)], as_of="2025-12-31")["shares"] == 0,
      "as_of ignore les mouvements postérieurs")

print("--- avis Natixis ---")
AVIS = """Versement dans votre PEE - Plan d'Épargne Entreprise au titre de l'année 2026
Placement Montant versé Abondement
Prime de partage de la valeur
EPARGNE ISR MONETAIRE I 1 000,00 250,00 04/08/2026 20,00000 60,0000 01/09/2031 Prélèvements sociaux à déduire - 50,00
IMPACT ISR PERFORMANCE I 500,00 04/08/2026 50,00000 10,0000 01/09/2031
Situation de vos avoirs au 05 août 2026
EPARGNE ISR MONETAIRE I 01/09/2030 20,00000 40,0000 800,00 04/08/2026
EPARGNE ISR MONETAIRE I 01/09/2031 20,00000 60,0000 1 200,00 04/08/2026
IMPACT ISR PERFORMANCE I 01/09/2031 50,00000 10,0000 500,00 04/08/2026
TOTAL* 2 500,00 €"""
p = natixis.parse(AVIS)
check(len(p["operations"]) == 2, "deux versements lus")
o = p["operations"][0]
check((o["amount"], o["employer_amount"], o["social_tax"], o["shares"]) == (1000, 250, 50, 60), "montants au format français")
check(p["operations"][1]["employer_amount"] == 0, "versement sans abondement")
check(o["date"] == "2026-08-04" and o["available_on"] == "2031-09-01", "dates ISO")
check(len(p["lots"]) == 3 and p["total"] == 2500, "situation des avoirs")
check(p["situation_date"] == "2026-08-05", "date de situation en toutes lettres")
check(p["category"] == "Prime de partage de la valeur", "nature de l'opération (pas l'en-tête Abondement)")
check(natixis.norm("Épargne ISR Monétaire I") == "EPARGNE ISR MONETAIRE I", "noms comparés sans accents")

print("--- pointage ---")
db.init()
with db.connect() as conn:
    conn.execute("INSERT INTO asset_registry (isin, name, asset_type, asset_class) VALUES ('X', 'ETF X', 'etf', 'etf')")
    conn.execute("INSERT INTO prices_last (isin, price, price_eur) VALUES ('X', 10, 10)")
    conn.execute("""INSERT INTO transactions (date, type, isin, name, shares, price, amount, account)
                    VALUES ('2026-01-05', 'buy', 'X', 'ETF X', 100, 9, 900, 'PEA')""")
    conn.commit()
r = checks.evaluate("PEA", "2026-10-01", [{"isin": "X", "shares": 100, "value": 1001}])
check(r["status"] == "ok", "quantité égale, cours dans la tolérance → concordant")
r = checks.evaluate("PEA", "2026-10-01", [{"isin": "X", "shares": 102, "value": 1020}])
check(r["status"] == "ecart" and r["lines"][0]["share_gap"] == 2, "écart de quantité détecté")
r = checks.evaluate("PEA", "2026-10-01", [{"isin": "X", "shares": 100, "value": 1100}])
check(r["share_gaps"] == 0 and r["price_gaps"] == 1, "écart de cours signalé séparément")
r = checks.evaluate("PEA", "2026-10-01", [{"isin": "X", "shares": 102, "value": 1020}])
saved = checks.commit(r, adjust=True)
held = valuation.replay(db.get_transactions("PEA"))["shares"]
check(saved["adjustments"] == 1 and held == 102 and saved["status"] == "ok", "rattrapage créé, pointage concordant")
check(valuation.check_state("PEA", {"date": "2026-01-01", "status": "ok", "declared_total": 1,
                                   "computed_total": 1})["state"] == "a_pointer",
      "pointage ancien → à pointer")

print(f"\n{'OK' if not fails else f'{fails} échec(s)'}")
sys.exit(1 if fails else 0)
