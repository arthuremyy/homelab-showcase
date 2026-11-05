"""Écran « Ce mois » — un seul appel. Mois en cours = période d'un salaire au suivant."""
from datetime import date, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field

import db
from services import forecast, views
from services.categorize import key_of

router = APIRouter(prefix="/api/budget")


class MonthIn(BaseModel):
    month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


@router.post("/overview")
async def overview(body: MonthIn):
    today = date.today()
    current = today.strftime("%Y-%m")
    month = body.month or current
    fixed = views.confirmed()
    by_id = {r["id"]: r for r in fixed}
    period = salary = None
    if month == current:
        # Fenêtre large : retrouver le dernier salaire et les fixes payés juste avant la période.
        window = views.with_party(views.ops_since((today - timedelta(days=80)).isoformat()))
        gone = views.with_party(views.vanished_pending())
    else:
        window = views.with_party(views.month_ops(month))
        gone = []
    for o in window + gone:                                # rattachée à la main : compte pour son fixe
        r = by_id.get(o.get("recurring_id"))
        if r:
            o["label"] = r["key"][:-2]
            if not o["category_locked"]:
                o.update(views.last_category(r["label"]))
    ops = window
    if month == current:
        main = max((r for r in fixed if r["amount"] > 0), key=lambda r: r["amount"], default=None)
        pay = [o for o in window if main and o["amount"] > 0 and key_of(o["label"], o["amount"]) == main["key"]]
        period = forecast.pay_period([date.fromisoformat(o["date"]) for o in pay], today)
        start = period["start"].isoformat()
        ops = [o for o in window if o["date"] >= start]
        if period["by"] == "salary":
            salary = {"id": main["id"], "amount": round(sum(o["amount"] for o in pay if o["date"] == start), 2)}
    anon = forecast.attach_anonymous(ops + gone, fixed)   # opération sans contrepartie → son fixe
    for o in ops + gone:
        if o["id"] in anon:
            r = anon[o["id"]]
            o.update(label=r["key"][:-2], **views.last_category(r["label"]))
    fixed_keys = {r["key"] for r in fixed}
    totals = forecast.month_totals(ops, views.kinds(), fixed_keys)

    # Dépenses par catégorie (remboursements déduits), avec le plafond éventuel.
    by_cat: dict[int | None, dict] = {}
    for o in ops:
        if (o.get("kind") or ("income" if o["amount"] > 0 else "expense")) != "expense":
            continue
        e = by_cat.setdefault(o["category_id"], {"id": o["category_id"],
                                                 "name": o["category"] or "Sans catégorie",
                                                 "spent": 0.0, "count": 0})
        e["spent"] += -o["amount"]
        e["count"] += 1
    budgets = {c["id"]: c["budget"] for c in db.categories()}
    avg = views.category_avg(month)
    # « Divers » est le repli de la catégorisation : ce qui y tombe reste à classer.
    cats = sorted(({**e, "spent": round(e["spent"], 2), "budget": budgets.get(e["id"]), "avg": avg.get(e["id"]),
                    "unsorted": e["id"] is None or e["name"] == "Divers"}
                   for e in by_cat.values() if e["spent"] > 0.005), key=lambda e: -e["spent"])
    # Catégories au solde positif (remboursements reçus…) : en déduction, affichées à part.
    credits = sorted(({"id": e["id"], "name": e["name"], "amount": round(-e["spent"], 2)}
                      for e in by_cat.values() if e["spent"] < -0.005), key=lambda e: -e["amount"])

    bal = views.balance()
    out = {
        "month": month, "current": month == current,
        "months": views.months_available(),
        "balance": bal,
        "totals": totals,
        "categories": cats,
        "credits": credits,
        "overdraft": forecast.overdraft(views.overdraft_ops()),
        "livret": views.livret(),
        "trend": views.trend(6),
        "bank": views.bank_status(),
        "suggestions": len(views.suggestions(today)),
        "fixed_count": len(fixed),
        "envelope": forecast.envelope(fixed, salary),
        "op_count": len(ops),
    }
    if month == current:
        presence = {r["id"]: r for r in views.with_presence(fixed, today)}
        pending = [{**r, "missing": presence[r["id"]]["missing"]}
                   for r in forecast.pending_in_period(window + gone, fixed, today, period["start"], period["end"])]
        out["period"] = {**period, "start": start, "end": period["end"].isoformat()}
        out["pending"] = pending
        out["remaining"] = forecast.remaining(bal["total"], pending)
        out["low"] = forecast.low_point(bal["total"], pending, today)
        out["spendable"] = forecast.spendable(out["low"], out["envelope"], totals["variable"])
        out["low_threshold"] = float(db.get_settings().get("low_balance") or 0)
    return out
