"""
Période en cours — calculs PURS (test_budget.py).

La période va d'un salaire au suivant (`pay_period`) : salaire et loyer tombent en fin de mois,
le mois calendaire comparerait les dépenses d'un mois au salaire qui arrive à sa toute fin.

  fin de mois prévue = solde actuel
                     + revenus fixes pas encore arrivés ce mois
                     − charges fixes pas encore passées ce mois
  reste à vivre      = revenus fixes − charges fixes (par mois, pour les dépenses courantes)
  dépensable         = min(point bas du mois, reste à vivre − dépenses courantes du mois)

Le solde retenu est le solde « disponible » de la banque : les opérations en
attente (PDNG) y sont déjà déduites, on ne les retranche donc pas une 2e fois.
"""
import re
from calendar import monthrange
from datetime import date, timedelta

from services.categorize import key_of

LATE_DAYS = 3   # un fixe attendu depuis plus de 3 jours est signalé « en retard »
TOLERANCE = 0.15
PAYDAY_MAX_AGE = 45   # au-delà, le salaire est jugé arrêté : repli sur le mois calendaire
EARLY_DAYS = 20       # un fixe payé jusqu'à 20 j avant son jour compte pour cette échéance


def add_month(d: date) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def pay_period(paydays: list[date], today: date) -> dict:
    """Du dernier salaire reçu à la veille du même jour le mois suivant. Salaire en retard :
    la période se prolonge jusqu'à son arrivée. Sans salaire récent : mois calendaire."""
    past = [p for p in paydays if p <= today and (today - p).days <= PAYDAY_MAX_AGE]
    start = max(past) if past else today.replace(day=1)
    end = max(add_month(start) - timedelta(days=1), today)
    return {"start": start, "end": end, "by": "salary" if past else "month",
            "days": (end - start).days + 1, "elapsed": (today - start).days + 1}


def due_date(day: int | None, start: date, end: date) -> date | None:
    """Échéance d'un fixe (jour du mois) dans la période, None s'il n'y tombe pas."""
    for y, m in ((start.year, start.month), (end.year, end.month)):
        d = date(y, m, min(day or 1, monthrange(y, m)[1]))
        if start <= d <= end:
            return d
    return None


def pending_in_period(ops: list[dict], recurring: list[dict], today: date, start: date, end: date) -> list[dict]:
    """Fixes dont l'échéance tombe dans la période et pas encore réglés. `ops` doit couvrir
    depuis `start − EARLY_DAYS` : un loyer payé deux jours avant le salaire reste réglé, un
    prélèvement du 25 passé le mois d'avant ne règle pas celui du 25 à venir."""
    due = []
    for r in recurring:
        d = due_date(r.get("day"), start, end)
        if d:
            due.append({**r, "due": d, "since": (d - timedelta(days=EARLY_DAYS)).isoformat()})
    out = [{**r, "due": r["due"].isoformat(), "late": (today - r["due"]).days > LATE_DAYS}
           for r in pending_fixed(ops, due, today)]
    for r in out:
        r.pop("since")
    return sorted(out, key=lambda r: r["due"])


def month_totals(ops: list[dict], kinds: dict[int, str], fixed_keys: set[str]) -> dict:
    """`ops` : opérations du mois [{amount, label, category_id}] ; `kinds` : {category_id: kind}.

    Les virements internes sont ignorés. Une dépense remboursée (montant positif
    dans une catégorie de dépense) vient en déduction des dépenses."""
    income = expenses = savings = fixed = 0.0
    for o in ops:
        kind = kinds.get(o.get("category_id"), "income" if o["amount"] > 0 else "expense")
        a = o["amount"]
        if kind == "transfer":
            continue
        if kind == "income":
            income += a
        elif kind == "savings":
            savings += -a
        else:
            expenses += -a
            if key_of(o["label"], a) in fixed_keys:
                fixed += -a
    rate = (income - expenses) / income if income > 0 else None
    return {
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "fixed": round(fixed, 2),
        "variable": round(expenses - fixed, 2),
        "savings": round(savings, 2),
        "net": round(income - expenses - savings, 2),
        "savings_rate": round(rate, 4) if rate is not None else None,
    }


def attach_anonymous(ops: list[dict], recurring: list[dict]) -> dict[int, dict]:
    """La banque envoie parfois une opération en attente sans contrepartie (« VIR INSTANTANE EMIS »
    pour le loyer). Elle est rattachée au fixe du même sens, pas encore réglé, à ±15 % du montant.
    Renvoie {id d'opération: fixe}."""
    seen = {key_of(o["label"], o["amount"]) for o in ops}
    free = [r for r in recurring if r["key"] not in seen]
    out: dict[int, dict] = {}
    for o in ops:
        if key_of(o["label"]).strip():
            continue
        want = abs(o["amount"])
        hit = min((r for r in free if (r["amount"] > 0) == (o["amount"] > 0)
                   and abs(abs(r["amount"]) - want) <= abs(r["amount"]) * TOLERANCE),
                  key=lambda r: abs(abs(r["amount"]) - want), default=None)
        if hit:
            out[o["id"]] = hit
            free.remove(hit)
    return out


def pending_fixed(ops: list[dict], recurring: list[dict], today: date) -> list[dict]:
    """Fixes confirmés pas encore vus ce mois-ci, avec leur état (à venir / en retard).

    `r["key"]` est la contrepartie qui règle le fixe. Un fixe seul sur sa contrepartie est
    réglé dès qu'une opération de celle-ci passe, quel que soit le montant (salaire réduit,
    loyer + taxe). Plusieurs fixes sur une même contrepartie :
      - montants distincts (Bouygues box + mobile) : chaque opération règle le fixe le plus proche ;
      - un seul virement pour plusieurs fixes (CAF : APL + prime) : réglés ensemble si les
        sommes concordent.
    `r["since"]` (facultatif) : seules les opérations à partir de cette date règlent ce fixe."""
    paid: dict[str, list[tuple[float, str]]] = {}
    for o in ops:
        paid.setdefault(key_of(o["label"], o["amount"]), []).append((abs(o["amount"]), o.get("date", "")))
    groups: dict[str, list[dict]] = {}
    for r in recurring:
        groups.setdefault(r["key"], []).append(r)

    out = []
    for k, rs in groups.items():
        amounts = list(paid.get(k, []))
        if len(rs) == 1:
            left = [] if any(d >= rs[0].get("since", "") for _, d in amounts) else rs
        else:
            left = []
            for r in sorted(rs, key=lambda r: -abs(r["amount"])):
                want = abs(r["amount"])
                hit = next((x for x in amounts if x[1] >= r.get("since", "") and abs(x[0] - want) <= want * TOLERANCE), None)
                if hit is None:
                    left.append(r)
                else:
                    amounts.remove(hit)
            want = sum(abs(r["amount"]) for r in left)
            since = min((r.get("since", "") for r in left), default="")
            rest = [a for a, d in amounts if d >= since]
            if left and rest and abs(sum(rest) - want) <= want * TOLERANCE:
                left = []
        for r in left:
            day = r.get("day") or 1
            out.append({**r, "late": today.day - day > LATE_DAYS})
    return sorted(out, key=lambda r: (r.get("day") or 1))


def remaining(balance: float | None, pending: list[dict]) -> float | None:
    if balance is None:
        return None
    return round(balance + sum(r["amount"] for r in pending), 2)


def low_point(balance: float | None, pending: list[dict], today: date) -> dict | None:
    """Point bas du mois : solde jour par jour en appliquant les fixes à venir à leur date
    (un fixe en retard est supposé tomber aujourd'hui). Sert à prévenir un découvert."""
    if balance is None:
        return None
    def when(r: dict) -> date:
        d = date.fromisoformat(r["due"]) if r.get("due") else today.replace(day=r.get("day") or today.day)
        return max(d, today)
    low, low_at, bal = balance, today, balance
    for r in sorted(pending, key=when):
        bal += r["amount"]
        if bal < low:
            low, low_at = bal, when(r)
    return {"amount": round(low, 2), "day": low_at.day, "date": low_at.isoformat()}


def envelope(fixed: list[dict], salary: dict | None = None) -> float | None:
    """Reste à vivre : revenus fixes − charges fixes. Ce qui reste pour les dépenses courantes.
    `salary` = {id, amount} du salaire qui ouvre la période : son montant réel remplace le
    montant prévu (le salaire varie d'un mois à l'autre). None sans fixe confirmé."""
    if not fixed:
        return None
    return round(sum(salary["amount"] if salary and r["id"] == salary["id"] else r["amount"]
                     for r in fixed), 2)


def spendable(low: dict | None, envelope: float | None, variable: float) -> dict | None:
    """Ce qui peut encore être dépensé ce mois-ci : le plus petit de deux plafonds,
      - « solde » : point bas du mois, pour ne pas passer à découvert ;
      - « budget » : reste à vivre mensuel moins les dépenses courantes déjà faites.
    Négatif = découvert prévu ou budget dépassé."""
    caps = []
    if low is not None:
        caps.append((low["amount"], "solde"))
    if envelope is not None:
        caps.append((round(envelope - variable, 2), "budget"))
    if not caps:
        return None
    amount, limit = min(caps)
    return {"amount": round(amount, 2), "limit": limit}


OVERDRAFT_DAYS = re.compile(r"NOMBRE JOURS DEBITEURS\s*:\s*(\d+)")


def overdraft(ops: list[dict]) -> dict:
    """Coût du découvert (intérêts débiteurs + commissions d'intervention, rétrocessions déduites)
    et jours à découvert du dernier arrêté trimestriel. `ops` : [{date, amount, label}]."""
    from services.categorize import parse_label
    cost, days, last = 0.0, None, None
    for o in sorted(ops, key=lambda o: o["date"]):
        up = o["label"].upper()
        if parse_label(o["label"])["overdraft"] or up.startswith("RETROCESSION INTERET"):
            cost += -o["amount"]
            m = OVERDRAFT_DAYS.search(up)
            if m:
                days, last = int(m.group(1)), o["date"]
    return {"cost": round(cost, 2), "days_last_quarter": days, "last_statement": last}
