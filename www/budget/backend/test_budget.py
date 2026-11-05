"""Tests purs (sans réseau ni base) : catégorisation, fixes, mois en cours, synchro.

    python3 test_budget.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test")
from services import categorize as cz, forecast as fc, recurring as rc  # noqa: E402
from services.sync import announced, still_vanished, parse, pick_balance, replace_unreferenced, with_ids  # noqa: E402
import sqlite3                                                             # noqa: E402

fails = 0


def check(ok, msg):
    global fails
    print(("  ✅ " if ok else "  ❌ ÉCHEC ") + msg)
    fails += 0 if ok else 1


print("--- normalisation et clés ---")
check(cz.normalize("CARTE X1234 01/10 Carrefour City") == "CARTE CARREFOUR CITY", "références retirées")
check(cz.key_of("PRLV SEPA FREE MOBILE ECH/011025 ID EMETTEUR/FR12ZZZ") ==
      cz.key_of("PRLV SEPA FREE MOBILE ECH/011125 ID EMETTEUR/FR12ZZZ") == "FREE MOBILE", "clé stable d'un mois à l'autre")
check(cz.key_of("CAF DU NORD VIR RECU CAF DU NORD APL") == "CAF NORD APL", "contrepartie répétée dédoublonnée")
check(cz.key_of("FREE MOBILE", -19.99).endswith(" -") and cz.key_of("FREE", 5).endswith(" +"), "sens dans la clé")

print("--- libellés Ma Banque ---")
P = cz.parse_label
check(P("CARTE X1234 30/09 CAFE DE LA GARE")["party"] == "CAFE DE LA GARE", "carte")
check(P("PAIEMENT CARTE DU 01/10 15:06 TABAC PRESSE GC")["party"] == "TABAC PRESSE GC", "carte en attente")
check(P("PRELEVEMENT EUROPEEN 9000000001 DE: TELECOM MOBILE ID: FR00ZZZ1 MOTIF: 09x REF: PA")["party"]
      == "TELECOM MOBILE", "prélèvement : DE: … ID:")
x = P("VIR RECU    1234567890S DE: ACME EUROPE REF: PAYROLL SAS     000000")
check(x["kind"] == "transfer_in" and x["party"] == "ACME EUROPE", "virement reçu")
x = P("000001 VIR INSTANTANE EMIS LOGITEL POUR: IMMO GESTION 30 09 BQ ABCD CPT 0002 DATE: 29/09/2026 REF:")
check(x["kind"] == "transfer_out" and x["party"] == "IMMO GESTION", "virement émis, arrêt au 1er nombre")
check(P("VIR INST RE 123 DE: MR DUPONT JEAN DATE: 21/09/2026 11:03 REF: NOT PROVIDED")["party"] == "MR DUPONT JEAN",
      "virement instantané reçu")
x = P("CARTE X1234 22/07 SUPERMERCADO CENTRAL USD")
check(x["foreign"] and x["party"] == "SUPERMERCADO CENTRAL", "devise étrangère repérée et retirée")
check(P("CARTE X1234 28/09 HOTEL CENTRAL EUR ESPAGNE")["foreign"], "pays étranger")
x = P("CARTE X1234 19/06 RESTO NEW YORK 40,00 USD ETATS UNIS 1 EUR=1,08 USD")
check(x["foreign"] and x["party"] == "RESTO NEW YORK", "devise après le montant")
check(P("CARTE X1234 TRANSF 14/08 Revolut**0000*")["party"] == "REVOLUT", "transfert carte")
check(P("CARTE X1234 RETRAIT DAB 25/09 17H34 CA CENTRE")["kind"] == "withdrawal", "retrait")
check(P("INTERETS DEBITEURS  01.04/30.06 CALCULES AU TAUX DE 20,00%")["overdraft"], "intérêts débiteurs")
check(P("COMMISSION D'INTERVENTION Calculée au 24/07/2026 pour : CARTE X1234")["overdraft"], "commission d'intervention")
check(cz.display("M ALEX MARTIN") == "Alex Martin", "affichage sans civilité")

print("--- catégorisation ---")
by = {"Revenus": 1, "Aides": 2, "Énergie": 3, "Transport": 4, "Restaurants": 5, "Divers": 6, "Courses": 7}
kw = {"Aides": ["CAF"], "Énergie": ["TOTALENERGIES"], "Transport": ["TOTAL"], "Restaurants": ["BRASSERIE"],
      "Revenus": ["SALAIRE"], "Courses": ["CARREFOUR"]}
m = lambda label, amt=-10, rules=(): cz.match(label, amt, list(rules), kw, by)  # noqa: E731
check(m("VIR RECU CAF DU NORD", 250) == 2, "CAF → Aides")
check(m("CARTE X1234 CAFE DE LA GARE") == 6, "« CAFE » ne déclenche pas « CAF »")
check(m("PRLV TOTALENERGIES ELEC") == 3, "le mot-clé le plus long gagne")
check(m("CARTE TOTAL ACCESS PARIS") == 4, "TOTAL seul → Transport")
check(m("VIR RECU 123 MOTIF SALAIRE SEPT", 2100) == 1, "salaire")
check(m("VIR RECU DUPONT", 40) == 1 and m("ACHAT INCONNU") == 6, "repli Revenus / Divers")
check(m("CARTE CARREFOUR CITY", rules=[{"pattern": "CARREFOUR CITY", "category_id": 5}]) == 5,
      "règle utilisateur prioritaire sur mot-clé")
by2 = {**by, "Épargne et investissement": 10, "Remboursements reçus": 11, "Virements à des proches": 12,
       "Voyages": 13, "Banque et frais": 14, "Retraits": 15}
m2 = lambda label, amt=-10: cz.match(label, amt, [], kw, by2, {"MARTIN", "ALEX"})  # noqa: E731
check(m2("VIR RECU 123 DE: M. ALEX MARTIN", 300) == 10, "virement depuis soi-même → épargne")
check(m2("000001 VIR EUROPEEN EMIS LOGITEL POUR: M. ALEX MARTIN 27 08 BQ 00000 CPT 1", -300) == 10,
      "virement vers soi-même → épargne")
check(m2("VIREMENT DECLIC SEUIL VERS COMPTE 00000 123") == 10, "épargne automatique")
check(m2("VIR INST RE 1 DE: MR DUPONT JEAN DATE: 21/09", 20) == 11, "particulier → remboursement reçu")
check(m2("000001 VIR INSTANTANE EMIS WERO POUR: JEAN DUPONT IBAN: XX", -20) == 12, "virement à un proche")
check(m2("VIR RECU 1 DE: ASSURANCES GROUPE FRANCE", 70) == 1, "organisation ≠ particulier")
check(m2("CARTE X1234 22/07 RESTO NEW YORK USD") == 13, "paiement à l'étranger → Voyages")
check(m2("COMMISSION D'INTERVENTION pour : CARTE X1234 22/07 CARREFOUR") == 14, "frais avant mot-clé")
check(m2("VIR RECU 1 DE: CAF DU NORD", 400) == 2, "CAF reste une aide")

print("--- détection des fixes ---")
today = date(2026, 10, 2)
ops = []
for mth, d in (("06", "05"), ("07", "05"), ("08", "06"), ("09", "05")):
    ops.append({"date": f"2026-{mth}-{d}", "amount": -19.99, "label": f"PRLV SEPA FREE MOBILE ECH/{d}{mth}26"})
    ops.append({"date": f"2026-{mth}-28", "amount": 2100.0 + int(mth), "label": "VIR RECU ACME SALAIRE"})
    for j in ("03", "10", "17", "24"):
        ops.append({"date": f"2026-{mth}-{j}", "amount": -42.0, "label": "CARTE CARREFOUR CITY"})
    ops.append({"date": f"2026-{mth}-06", "amount": 150.0, "label": "CAF DU NORD VIR RECU CAF DU NORD PRIME ACTIVITE"})
    ops.append({"date": f"2026-{mth}-06", "amount": 80.0, "label": "CAF DU NORD VIR RECU CAF DU NORD APL"})
ops.append({"date": "2026-06-12", "amount": -9.99, "label": "NETFLIX"})       # abonnement arrêté
ops.append({"date": "2026-07-12", "amount": -9.99, "label": "NETFLIX"})
s = {x["key"]: x for x in rc.detect(ops, today)}
check("FREE MOBILE -" in s and s["FREE MOBILE -"]["amount"] == -19.99 and s["FREE MOBILE -"]["day"] == 5,
      "abonnement mensuel détecté (montant, jour)")
check(any(k.startswith("ACME") and v["amount"] > 2100 for k, v in s.items()), "salaire variable (±15 %) détecté")
check(not any("CARREFOUR" in k for k in s), "commerce fréquent ≠ fixe")
mix = [{"date": f"2026-{m}-{d:02d}", "amount": -a, "label": "CARREFOUR GDCLE"}
       for m in ("07", "08", "09") for d, a in ((3, 10.6), (14, 29.4), (22, 21.9), (27, 55))]
check(not rc.detect(mix, today), "achats réguliers à montants récurrents ≠ fixes")
check("CAF NORD PRIME ACTIVITE +" in s and "CAF NORD APL +" in s, "deux aides CAF distinctes le même jour")
check(not any("NETFLIX" in k for k in s), "fixe arrêté depuis > 45 j ignoré")
check(not rc.detect(ops, today, set(s)), "clés connues non reproposées")
hf = [{"date": f"2026-{m}-09", "amount": -a, "label": "TELECOM MOBILE"}
              for m, a in (("06", 18.99), ("07", 22.89), ("08", 18.99), ("09", 19.02), ("10", 19.66))]
hf += [{"date": f"2026-{m}-29", "amount": -24.99, "label": "TELECOM MOBILE"} for m in ("06", "07", "08", "09")]
check(not rc.detect(hf, date(2026, 10, 12), {"TELECOM MOBILE 18.99 -", "TELECOM MOBILE 24.99 -", "TELECOM MOBILE -"}),
      "hors forfait : fixe connu à 18,99 non reproposé à 19,02")
sal = [{"date": d, "amount": a, "label": "ACME EUROPE"} for d, a in
       (("2026-05-28", 2010), ("2026-06-29", 1890), ("2026-08-28", 1070), ("2026-09-29", 2005))]
check(any(x["key"] == "ACME EUROPE +" for x in rc.detect(sal, today)), "salaire malgré un mois sauté et un mois partiel")

bt = []
for mth in ("05", "06", "07", "08", "09"):
    bt.append({"date": f"2026-{mth}-09", "amount": -18.99, "label": "TELECOM MOBILE"})
    bt.append({"date": f"2026-{mth}-29", "amount": -24.99, "label": "TELECOM MOBILE"})
sb = rc.detect(bt, today)
check(sorted(x["amount"] for x in sb) == [-24.99, -18.99] and len({x["key"] for x in sb}) == 2
      and all(x["match_key"] == "TELECOM MOBILE -" for x in sb), "deux prélèvements sous un même libellé")
two = [{"key": "TELECOM MOBILE -", "amount": -24.99, "day": 29}, {"key": "TELECOM MOBILE -", "amount": -18.99, "day": 9}]
p2 = fc.pending_fixed([{"label": "TELECOM MOBILE", "amount": -18.99}], two, date(2026, 10, 12))
check([x["amount"] for x in p2] == [-24.99], "le 1er prélèvement ne règle pas le 2e")
caf = [{"key": "CAF NORD +", "amount": 200, "day": 5}, {"key": "CAF NORD +", "amount": 80.55, "day": 5}]
check(not fc.pending_fixed([{"label": "CAF NORD", "amount": 280.55}], caf, date(2026, 10, 12)),
      "un virement CAF règle APL + prime")
check(not fc.pending_fixed([{"label": "ACME", "amount": 1000}], [{"key": "ACME +", "amount": 2000, "day": 29}],
                           date(2026, 8, 30)), "fixe seul réglé même à montant réduit")

print("--- mois en cours ---")
kinds = {1: "income", 2: "income", 3: "expense", 8: "savings", 9: "transfer"}
month = [
    {"amount": 2100, "label": "VIR RECU ACME SALAIRE", "category_id": 1},
    {"amount": 250, "label": "CAF", "category_id": 2},
    {"amount": -19.99, "label": "PRLV SEPA FREE MOBILE", "category_id": 3},
    {"amount": -80.01, "label": "CARTE CARREFOUR", "category_id": 3},
    {"amount": 10, "label": "AVOIR CARREFOUR", "category_id": 3},
    {"amount": -300, "label": "TRADE REPUBLIC", "category_id": 8},
    {"amount": -500, "label": "VIR LIVRET", "category_id": 9},
]
t = fc.month_totals(month, kinds, {"FREE MOBILE -"})
check(t["income"] == 2350 and t["expenses"] == 90 and t["fixed"] == 19.99, f"totaux {t}")
check(t["savings"] == 300 and t["net"] == 1960, "épargne à part, virements internes ignorés")
rec = [{"key": "FREE MOBILE -", "amount": -19.99, "day": 5}, {"key": "LOYER -", "amount": -650, "day": 1},
       {"key": "EDF -", "amount": -60, "day": 20}]
rent = [{"key": "IMMO GESTION -", "label": "Immo Gestion", "amount": -800.24, "day": 30},
        {"key": "EDF -", "label": "Edf", "amount": -58.10, "day": 25}]
anon = [{"id": 1, "label": "VIR INSTANTANE EMIS", "amount": -810.26}, {"id": 2, "label": "VIR INSTANTANE EMIS", "amount": -20.0}]
check(fc.attach_anonymous(anon, rent) == {1: rent[0]}, "virement sans contrepartie rattaché au loyer (±15 %)")
check(not fc.attach_anonymous(anon[:1] + [{"id": 3, "label": "IMMO GESTION", "amount": -800.24}], rent).get(1),
      "loyer déjà réglé : virement anonyme non rattaché")
p = fc.pending_fixed(month, rec, date(2026, 10, 10))
check([x["key"] for x in p] == ["LOYER -", "EDF -"], "fixes restants")
check(p[0]["late"] and not p[1]["late"], "loyer en retard, EDF à venir")
check(fc.remaining(1000, p) == 290, "fin de mois prévue = solde + fixes restants")

lp = fc.low_point(100, [{"amount": -800, "day": 28}, {"amount": 2000, "day": 29}], date(2026, 10, 2))
check((lp["amount"], lp["day"]) == (-700, 28), f"point bas avant le salaire {lp}")
pp = fc.pay_period([date(2026, 9, 29), date(2026, 10, 28)], date(2026, 10, 29))
check((pp["start"], pp["end"], pp["by"], pp["elapsed"]) == (date(2026, 10, 28), date(2026, 11, 27), "salary", 2),
      f"période : du salaire au mois suivant {pp}")
check(fc.pay_period([date(2026, 10, 28)], date(2026, 11, 29))["end"] == date(2026, 11, 29), "salaire en retard : période prolongée")
check(fc.pay_period([date(2026, 6, 28)], date(2026, 10, 29))["start"] == date(2026, 10, 1), "sans salaire récent : mois calendaire")
s0, e0 = date(2026, 10, 28), date(2026, 11, 27)
check(fc.due_date(30, s0, e0) == date(2026, 10, 30) and fc.due_date(5, s0, e0) == date(2026, 11, 5)
      and fc.due_date(28, date(2026, 11, 29), date(2026, 12, 28)) == date(2026, 12, 28), "échéance d'un fixe dans la période")
fx = [{"key": "IMMO GESTION -", "amount": -810, "day": 30}, {"key": "EDF -", "amount": -63, "day": 25},
      {"key": "ACME +", "amount": 2100, "day": 29},
      {"key": "TELECOM -", "amount": -24.99, "day": 29}, {"key": "TELECOM -", "amount": -18.99, "day": 9}]
pend = fc.pending_in_period([{"date": "2026-10-26", "label": "IMMO GESTION", "amount": -810},
                             {"date": "2026-10-25", "label": "EDF", "amount": -63},
                             {"date": "2026-10-28", "label": "ACME", "amount": 2100},
                             {"date": "2026-10-09", "label": "TELECOM", "amount": -19.66},
                             {"date": "2026-10-29", "label": "TELECOM", "amount": -24.99}], fx, date(2026, 10, 29), s0, e0)
check([(r["key"], r["due"]) for r in pend] == [("TELECOM -", "2026-11-09"), ("EDF -", "2026-11-25")],
      f"loyer payé juste avant le salaire réglé ; EDF du 25/10 ne règle pas celui du 25/11 {pend}")
check(fc.envelope([{"id": 1, "amount": 2000}, {"id": 2, "amount": -800}], {"id": 1, "amount": 2100}) == 1300,
      "reste à vivre avec le salaire réellement reçu")
check(fc.envelope([{"amount": 2000}, {"amount": -800}, {"amount": -30}]) == 1170 and fc.envelope([]) is None,
      "reste à vivre = revenus fixes − charges fixes")
check(fc.spendable({"amount": 88, "day": 2}, 800, 140) == {"amount": 88, "limit": "solde"}, "dépensable limité par le solde")
check(fc.spendable({"amount": 900, "day": 2}, 800, 140) == {"amount": 660, "limit": "budget"}, "dépensable limité par le budget")
check(fc.spendable(None, None, 0) is None and fc.spendable(None, 800, 900)["amount"] == -100, "sans solde, budget seul")
od = fc.overdraft([{"date": "2026-07-01", "amount": -12.3, "label": "INTERETS DEBITEURS 01.04/30.06 NOMBRE JOURS DEBITEURS :  21"},
                   {"date": "2026-07-24", "amount": -8, "label": "COMMISSION D'INTERVENTION Calculée au 24/07"},
                   {"date": "2026-07-30", "amount": 2.3, "label": "RETROCESSION INTERET DEBITEURS AU 13/04/26"}])
check(od == {"cost": 18.0, "days_last_quarter": 21, "last_statement": "2026-07-01"}, f"coût du découvert {od}")

print("--- synchronisation ---")
t1 = {"transaction_amount": {"amount": "12.50", "currency": "EUR"}, "credit_debit_indicator": "DBIT",
      "status": "BOOK", "booking_date": "2026-10-01", "remittance_information": ["CARTE X1234 BRASSERIE"],
      "entry_reference": "ABC"}
o = parse(t1, "u1")
check(o["amount"] == -12.5 and o["label"] == "CARTE X1234 BRASSERIE" and o["status"] == "BOOK", "débit signé")
twins = with_ids([parse({**t1, "entry_reference": None}, "u1"), parse({**t1, "entry_reference": None}, "u1")])
check(twins[0]["ext_id"] != twins[1]["ext_id"], "deux achats identiques le même jour restent distincts")
check(with_ids([o])[0]["ext_id"] == "eb:u1:ABC", "référence bancaire utilisée")
c = sqlite3.connect(":memory:")
c.row_factory = sqlite3.Row
c.execute("CREATE TABLE operations (id INTEGER PRIMARY KEY, ext_id TEXT UNIQUE, account_uid TEXT, date TEXT, "
          "amount REAL, counterparty TEXT, category_id INTEGER, category_locked INTEGER DEFAULT 0, source TEXT DEFAULT 'bank', "
          "recurring_id INTEGER)")
c.execute("INSERT INTO operations (ext_id, account_uid, date, amount, counterparty, category_id, category_locked) "
          "VALUES ('h:a', 'u1', '2026-10-09', -19.66, 'Telecom Mobile', 7, 1), "
          "('h:b', 'u1', '2026-10-09', -5.0, 'Telecom Mobile', NULL, 0)")
nid = c.execute("INSERT INTO operations (ext_id, account_uid, date, amount, counterparty) "
                "VALUES ('eb:u1:R', 'u1', '2026-10-09', -19.66, 'Telecom Mobile')").lastrowid
replace_unreferenced(c, nid, {"eb:u1:R"})
rows = {r["ext_id"]: dict(r) for r in c.execute("SELECT * FROM operations")}
check(set(rows) == {"h:b", "eb:u1:R"} and rows["eb:u1:R"]["category_id"] == 7 and rows["eb:u1:R"]["category_locked"],
      "opération sans référence remplacée par sa version référencée (catégorie gardée)")
c.execute("INSERT INTO operations (ext_id, account_uid, date, amount, counterparty) VALUES ('h:c', 'u1', '2026-10-09', -19.66, 'Telecom Mobile')")
replace_unreferenced(c, nid, {"h:c"})
check(c.execute("SELECT COUNT(*) FROM operations WHERE ext_id = 'h:c'").fetchone()[0] == 1,
      "opération de la passe en cours jamais retirée")
nid = c.execute("INSERT INTO operations (ext_id, account_uid, date, amount, counterparty) "
                "VALUES ('eb:u1:S', 'u1', '2026-10-20', -7.5, 'Pret Banque Express Financement E')").lastrowid
c.execute("INSERT INTO operations (ext_id, account_uid, date, amount, counterparty) VALUES "
          "('h:d', 'u1', '2026-10-20', -7.5, 'Pret Banque Express Financement'), "
          "('h:e', 'u1', '2026-10-20', -7.5, 'Pret Banq')")
replace_unreferenced(c, nid, set())
left = {r[0] for r in c.execute("SELECT ext_id FROM operations WHERE date = '2026-10-20'")}
check(left == {"eb:u1:S", "h:e"}, "contrepartie tronquée par le libellé court reconnue (au mot près)")
c.execute("INSERT INTO operations (ext_id, account_uid, date, amount, counterparty) "
          "VALUES ('h:f', 'u1', '2026-10-26', -58.10, 'Edf Clients Particuliers')")
pd = {"account_uid": "u1", "date": "2026-10-26", "amount": -58.10, "counterparty": "Edf Clients Particuliers"}
check(announced(c, pd) and not announced(c, {**pd, "amount": -10.0}),
      "opération en attente déjà annoncée sans référence : pas de doublon")
rent = {"ext_id": "p:x", "date": "2026-10-29", "amount": -810.26}
check(still_vanished([rent], [], date(2026, 10, 30)) == [rent]
      and not still_vanished([rent], [{"date": "2026-10-30", "amount": -810.26}], date(2026, 10, 30))
      and not still_vanished([rent], [], date(2026, 11, 6)),
      "loyer disparu des opérations en attente : gardé jusqu'à sa version comptabilisée (7 j max)")
check(pick_balance([{"balance_type": "CLBD", "balance_amount": {"amount": "10"}},
                    {"balance_type": "ITAV", "balance_amount": {"amount": "7"}}]) == 7.0, "solde disponible prioritaire")

print("--- consentement renouvelé, opérations en attente ---")
from services.sync import rattacher_compte, pending_date, with_ids                 # noqa: E402
_c = sqlite3.connect(":memory:")
_c.row_factory = sqlite3.Row
_c.executescript("""CREATE TABLE accounts (uid TEXT PRIMARY KEY);
CREATE TABLE operations (id INTEGER PRIMARY KEY, ext_id TEXT UNIQUE, account_uid TEXT, date TEXT, amount REAL,
  label TEXT, status TEXT, source TEXT DEFAULT 'bank');""")
_c.execute("INSERT INTO accounts VALUES ('old')")
_ops = with_ids([{"account_uid": "old", "date": "2026-10-01", "amount": -9.0, "label": "A", "status": "BOOK", "ref": "R1"},
                 {"account_uid": "old", "date": "2026-10-02", "amount": -5.0, "label": "B", "status": "BOOK", "ref": None}])
for _o in _ops:
    _c.execute("INSERT INTO operations (ext_id, account_uid, date, amount, label, status) VALUES (?,?,?,?,?,?)",
               (_o["ext_id"], "old", _o["date"], _o["amount"], _o["label"], _o["status"]))
check(rattacher_compte(_c, "old", "new") == 2, "historique déplacé vers le nouvel uid")
_again = with_ids([{"account_uid": "new", "date": "2026-10-01", "amount": -9.0, "label": "A", "status": "BOOK", "ref": "R1"},
                   {"account_uid": "new", "date": "2026-10-02", "amount": -5.0, "label": "B", "status": "BOOK", "ref": None}])
for _o in _again:
    _c.execute("INSERT OR IGNORE INTO operations (ext_id, account_uid, date, amount, label, status) VALUES (?,?,?,?,?,?)",
               (_o["ext_id"], "new", _o["date"], _o["amount"], _o["label"], _o["status"]))
check(_c.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 2, "relecture après renouvellement : aucun doublon")
check(_c.execute("SELECT COUNT(*) FROM accounts WHERE uid = 'old'").fetchone()[0] == 0, "ancien compte retiré")
check(pending_date("PAIEMENT CARTE DU 28/10 MAGASIN", date(2026, 11, 3)) == "2026-10-28", "date d'achat lue dans le libellé")
check(pending_date("PAIEMENT CARTE DU 28/12 MAGASIN", date(2026, 1, 3)) == "2025-12-28", "achat de l'an passé")
check(pending_date("VIR INSTANTANE EMIS", date(2026, 11, 3)) is None, "pas de date : rien d'inventé")
_p = lambda d: with_ids([{"account_uid": "u", "date": d, "amount": -1.0, "label": "X", "status": "PDNG", "ref": None}])[0]["ext_id"]
check(_p("2026-11-03") == _p("2026-11-04"), "identifiant d'une opération en attente stable d'un jour à l'autre")

print(f"\n{fails} échec(s)" if fails else "\nTous les tests passent.")
sys.exit(1 if fails else 0)
