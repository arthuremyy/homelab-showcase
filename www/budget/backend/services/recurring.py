"""
Fixes (revenus, charges, aides récurrents) — détection PURE (test_recurring.py).

Un fixe est un même libellé (clé `categorize.key_of`, sens compris) qui revient
environ tous les mois pour un montant stable. La détection ne fait que
PROPOSER : l'utilisateur confirme ou ignore, rien n'est pris en compte d'office.
"""
from datetime import date
from statistics import median

from services.categorize import key_of

WINDOW_DAYS = 130        # ~4 mois d'historique
TOLERANCE = 0.15         # ±15 % autour du montant médian
MIN_MONTHS = 2
GAP_MIN, GAP_MAX = 20, 40
STALE_DAYS = 45
MAX_PER_MONTH = 2.2      # au plus deux fixes sous un même libellé (box + mobile)          # plus vu depuis : fixe arrêté, on ne le propose plus


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def detect(ops: list[dict], today: date, known_keys: set[str] | None = None) -> list[dict]:
    """`ops` : [{date, amount, label}] (opérations comptabilisées, hors virements internes).
    Renvoie les suggestions triées par montant absolu décroissant."""
    known_keys = known_keys or set()
    groups: dict[str, list[dict]] = {}
    for o in ops:
        if (today - _d(o["date"])).days > WINDOW_DAYS or not o["amount"]:
            continue
        k = key_of(o["label"], o["amount"])
        if k.strip(" +-"):
            groups.setdefault(k, []).append(o)

    out = []
    for k, g in groups.items():
        # Un commerce fréquenté plusieurs fois par mois n'est pas un fixe — vérifié sur tout
        # le libellé, sinon le découpage par montant isolerait des achats réguliers.
        if len(g) > len({o["date"][:7] for o in g}) * MAX_PER_MONTH or k.startswith("RETRAIT DAB"):
            continue
        found = [s for c in _clusters(g) if (s := _evaluate(c, today))]
        for s in found:
            # Plusieurs fixes sous un même libellé (Bouygues : box + mobile) : clé propre
            # distincte par montant, tous réglés par la même contrepartie.
            own = k if len(found) == 1 else f"{k[:-2]} {abs(s['amount']):.2f}{k[-2:]}"
            if own in known_keys or (len(found) == 1 and k in known_keys) or _known_near(k, s["amount"], known_keys):
                continue
            out.append({"key": own, "match_key": k, "label": label_of(k), **s})
    return sorted(out, key=lambda s: -abs(s["amount"]))


def _known_near(k: str, amount: float, known_keys: set[str]) -> bool:
    """Fixe déjà connu sous ce libellé à un montant proche (±TOLERANCE) : un hors forfait
    déplace la médiane (18,99 → 19,02) sans faire un nouveau fixe."""
    head, tail = k[:-2] + " ", k[-2:]
    for kk in known_keys:
        if kk.startswith(head) and kk.endswith(tail):
            try:
                a = float(kk[len(head):-len(tail)])
            except ValueError:
                continue
            if abs(abs(amount) - a) <= a * TOLERANCE:
                return True
    return False


def _clusters(g: list[dict]) -> list[list[dict]]:
    """Regroupe les opérations d'un même libellé par montant (±TOLERANCE)."""
    out: list[list[dict]] = []
    for o in sorted(g, key=lambda o: abs(o["amount"])):
        if out and abs(o["amount"]) <= abs(out[-1][0]["amount"]) * (1 + TOLERANCE):
            out[-1].append(o)
        else:
            out.append([o])
    return out


def _evaluate(g: list[dict], today: date) -> dict | None:
    """Un groupe de montants proches est-il un fixe mensuel ?"""
    med = median(abs(o["amount"]) for o in g)
    close = sorted((o for o in g if abs(abs(o["amount"]) - med) <= med * TOLERANCE), key=lambda o: o["date"])
    months = {o["date"][:7] for o in close}
    if len(months) < MIN_MONTHS:
        return None
    # Un commerce fréquenté plusieurs fois par mois n'est pas un fixe.
    if len(g) > len(months) * 1.5:
        return None
    # Un mois sauté (salaire versé autrement, loyer payé en double) ne doit pas suffire
    # à écarter un fixe : la majorité des écarts doit être mensuelle.
    gaps = [(_d(b["date"]) - _d(a["date"])).days for a, b in zip(close, close[1:])]
    if not gaps or sum(GAP_MIN <= x <= GAP_MAX for x in gaps) < max(1, round(len(gaps) * 0.6)):
        return None
    last = close[-1]
    if (today - _d(last["date"])).days > STALE_DAYS:
        return None
    sign = 1 if last["amount"] > 0 else -1
    return {
        "amount": round(sign * median(abs(o["amount"]) for o in close), 2),
        "day": int(median(_d(o["date"]).day for o in close)),
        "months": len(months),
        "last_date": last["date"][:10],
    }


def label_of(key: str) -> str:
    """« FREE MOBILE - » → « Free Mobile »."""
    return " ".join(w.capitalize() for w in key.rstrip(" +-").split()) or "Sans libellé"
