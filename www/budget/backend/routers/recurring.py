"""Fixes : revenus, charges et aides qui reviennent chaque mois."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import db
from services import views

router = APIRouter(prefix="/api/budget")


class ConfirmIn(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    match_key: str | None = Field(default=None, max_length=120)
    label: str = Field(min_length=1, max_length=80)
    amount: float = Field(ne=0, gt=-1_000_000, lt=1_000_000)
    day: int | None = Field(default=None, ge=1, le=31)


class UpdateIn(BaseModel):
    id: int
    label: str = Field(min_length=1, max_length=80)
    amount: float = Field(ne=0, gt=-1_000_000, lt=1_000_000)
    day: int | None = Field(default=None, ge=1, le=31)
    match_key: str | None = Field(default=None, max_length=120)


class AddIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    amount: float = Field(ne=0, gt=-1_000_000, lt=1_000_000)
    day: int | None = Field(default=None, ge=1, le=31)
    match_key: str | None = Field(default=None, max_length=120)


class KeyIn(BaseModel):
    key: str = Field(min_length=1, max_length=120)


class IdIn(BaseModel):
    id: int


@router.get("/recurring")
async def recurring():
    return {"confirmed": views.with_presence(views.confirmed()), "suggestions": views.suggestions(),
            "parties": views.parties()}


@router.post("/recurring/confirm")
async def confirm(body: ConfirmIn):
    with db.connect() as c:
        match = body.match_key if body.match_key and body.match_key != body.key else None
        c.execute("INSERT INTO recurring (key, match_key, label, amount, day, status) VALUES (?,?,?,?,?, 'confirmed') "
                  "ON CONFLICT(key) DO UPDATE SET match_key = excluded.match_key, label = excluded.label, "
                  "amount = excluded.amount, day = excluded.day, status = 'confirmed'",
                  (body.key, match, body.label.strip(), round(body.amount, 2), body.day))
    return {"ok": True}


@router.post("/recurring/add")
async def add(body: AddIn):
    """Fixe saisi à la main (pas encore vu à la banque) : clé dérivée du libellé."""
    from services.categorize import key_of
    key = key_of(body.label, body.amount)
    if not key.strip(" +-"):
        raise HTTPException(422, "Libellé trop court")
    await confirm(ConfirmIn(key=key, label=body.label, amount=body.amount, day=body.day))
    with db.connect() as c:
        c.execute("UPDATE recurring SET match_key = ? WHERE key = ?", (body.match_key or None, key))
    return {"ok": True}


@router.post("/recurring/update")
async def update(body: UpdateIn):
    """Le sens fait partie de la clé : passer un montant de + à - change la clé propre."""
    from services.categorize import key_of
    with db.connect() as c:
        r = c.execute("SELECT key, match_key FROM recurring WHERE id = ?", (body.id,)).fetchone()
        if not r:
            raise HTTPException(404, "Fixe introuvable")
        sign = " +" if body.amount > 0 else " -"
        own = r["key"][:-2] + sign if r["key"].endswith((" +", " -")) else key_of(body.label, body.amount)
        match = body.match_key or (r["match_key"] if r["match_key"] and r["match_key"].endswith(sign) else None)
        try:
            n = c.execute("UPDATE recurring SET key = ?, label = ?, amount = ?, day = ?, match_key = ? WHERE id = ?",
                          (own, body.label.strip(), round(body.amount, 2), body.day,
                           None if match == own else match, body.id)).rowcount
        except Exception:                                       # noqa: BLE001
            raise HTTPException(409, "Un autre fixe porte déjà ce libellé")
    if not n:
        raise HTTPException(404, "Fixe introuvable")
    return {"ok": True}


@router.post("/recurring/ignore")
async def ignore(body: KeyIn):
    """Suggestion écartée : elle ne sera plus proposée."""
    with db.connect() as c:
        c.execute("INSERT INTO recurring (key, label, amount, status) VALUES (?, ?, 0, 'ignored') "
                  "ON CONFLICT(key) DO UPDATE SET status = 'ignored'", (body.key, body.key))
    return {"ok": True}


@router.post("/recurring/delete")
async def delete(body: IdIn):
    with db.connect() as c:
        c.execute("DELETE FROM recurring WHERE id = ?", (body.id,))
    return {"ok": True}


class LinkIn(BaseModel):
    id: int
    op_id: int
    update_amount: bool = True


class OpIn(BaseModel):
    op_id: int


@router.post("/recurring/candidates")
async def candidates(body: IdIn):
    """Opérations des 40 derniers jours (la période court d'un salaire au suivant), même sens
    que le fixe, les plus proches en montant d'abord."""
    from datetime import date, timedelta
    with db.connect() as c:
        r = c.execute("SELECT amount FROM recurring WHERE id = ?", (body.id,)).fetchone()
        if not r:
            raise HTTPException(404, "Fixe introuvable")
        rows = c.execute(
            "SELECT id, date, amount, COALESCE(counterparty, label) AS label, status, recurring_id FROM operations "
            "WHERE date >= ? AND (amount > 0) = ? ORDER BY date DESC",
            ((date.today() - timedelta(days=40)).isoformat(), r["amount"] > 0)).fetchall()
    ops = sorted((dict(x) for x in rows), key=lambda o: abs(abs(o["amount"]) - abs(r["amount"])))
    return {"operations": ops[:20]}


@router.post("/recurring/link")
async def link(body: LinkIn):
    """Rattache une opération à un fixe : il est réglé ce mois-ci et, si le libellé est lisible,
    reconnu tout seul les mois suivants (nouvel émetteur du salaire). Le montant suit (loyer augmenté)."""
    from services.categorize import key_of
    with db.connect() as c:
        r = c.execute("SELECT id, key, label, amount FROM recurring WHERE id = ? AND status = 'confirmed'",
                      (body.id,)).fetchone()
        o = c.execute("SELECT id, date, amount, COALESCE(counterparty, label) AS party, category_locked "
                      "FROM operations WHERE id = ?", (body.op_id,)).fetchone()
        if not r or not o:
            raise HTTPException(404, "Fixe ou opération introuvable")
        if (r["amount"] > 0) != (o["amount"] > 0):
            raise HTTPException(422, "Une entrée ne peut pas régler une charge (et inversement)")
        c.execute("UPDATE operations SET recurring_id = NULL WHERE recurring_id = ? AND date >= date(?, '-25 days')",
                  (r["id"], o["date"]))
        c.execute("UPDATE operations SET recurring_id = ? WHERE id = ?", (r["id"], o["id"]))
        k = key_of(o["party"], o["amount"])
        if k.strip(" +-"):
            c.execute("UPDATE recurring SET match_key = ? WHERE id = ?", (None if k == r["key"] else k, r["id"]))
        if body.update_amount:
            c.execute("UPDATE recurring SET amount = ? WHERE id = ?", (round(o["amount"], 2), r["id"]))
        cat = views.last_category(r["label"])
        if cat and not o["category_locked"]:
            c.execute("UPDATE operations SET category_id = ?, category_locked = 1 WHERE id = ?",
                      (cat["category_id"], o["id"]))
    return {"ok": True}


@router.post("/recurring/unlink")
async def unlink(body: OpIn):
    with db.connect() as c:
        c.execute("UPDATE operations SET recurring_id = NULL WHERE id = ?", (body.op_id,))
    return {"ok": True}
