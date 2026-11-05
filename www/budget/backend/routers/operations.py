"""Opérations, catégories et règles."""
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import db
from services import categorize, sync, views

router = APIRouter(prefix="/api/budget")

KINDS = {"income", "expense", "savings", "transfer"}


class ListIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


class CategorizeIn(BaseModel):
    id: int
    category_id: int
    remember: bool = False


class ManualIn(BaseModel):
    date: date
    amount: float = Field(ne=0, gt=-1_000_000, lt=1_000_000)
    label: str = Field(min_length=1, max_length=200)
    category_id: int | None = None


class IdIn(BaseModel):
    id: int


class CategoryIn(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=60)
    kind: str
    budget: float | None = Field(default=None, ge=0, lt=1_000_000)


@router.post("/operations/list")
async def list_ops(body: ListIn):
    return {"operations": views.month_ops(body.month), "categories": db.categories(),
            "months": views.months_available()}


@router.post("/operations/categorize")
async def set_category(body: CategorizeIn):
    """Catégorie posée à la main. `remember` : règle sur le libellé, appliquée à
    toutes les opérations non verrouillées qui le partagent (passées et futures)."""
    with db.connect() as c:
        o = c.execute("SELECT label, counterparty FROM operations WHERE id = ?", (body.id,)).fetchone()
        if not o or not c.execute("SELECT 1 FROM categories WHERE id = ?", (body.category_id,)).fetchone():
            raise HTTPException(404, "Opération ou catégorie introuvable")
        c.execute("UPDATE operations SET category_id = ?, category_locked = 1 WHERE id = ?",
                  (body.category_id, body.id))
        pattern, changed = None, 0
        if body.remember:
            pattern = categorize.key_of(o["counterparty"] or o["label"])
            if pattern:
                c.execute("INSERT INTO rules (pattern, category_id) VALUES (?, ?) "
                          "ON CONFLICT(pattern) DO UPDATE SET category_id = excluded.category_id",
                          (pattern, body.category_id))
                changed = sync.categorize_pending(c, only_null=False)
    return {"ok": True, "rule": pattern, "changed": changed}


@router.post("/operations/add")
async def add_manual(body: ManualIn):
    """Opération saisie (espèces, compte non relié…)."""
    import uuid
    with db.connect() as c:
        c.execute("INSERT OR IGNORE INTO accounts (uid, name, active) VALUES ('manual', 'Saisies', 0)")
        cur = c.execute(
            "INSERT INTO operations (ext_id, account_uid, date, amount, label, status, category_id, "
            "category_locked, source) VALUES (?, 'manual', ?, ?, ?, 'BOOK', ?, ?, 'manual')",
            (f"m:{uuid.uuid4().hex}", body.date.isoformat(), round(body.amount, 2), body.label.strip(),
             body.category_id, 1 if body.category_id else 0))
        if not body.category_id:
            sync.categorize_pending(c)
    return {"ok": True, "id": cur.lastrowid}


@router.post("/operations/delete")
async def delete_manual(body: IdIn):
    """Seules les saisies manuelles se suppriment : la banque fait foi pour le reste."""
    with db.connect() as c:
        n = c.execute("DELETE FROM operations WHERE id = ? AND source = 'manual'", (body.id,)).rowcount
    if not n:
        raise HTTPException(404, "Saisie manuelle introuvable")
    return {"ok": True}


@router.get("/categories")
async def categories():
    return {"categories": db.categories(), "rules": db.user_rules()}


@router.post("/categories/save")
async def save_category(body: CategoryIn):
    if body.kind not in KINDS:
        raise HTTPException(422, "Nature inconnue")
    with db.connect() as c:
        try:
            if body.id:
                c.execute("UPDATE categories SET name = ?, kind = ?, budget = ? WHERE id = ?",
                          (body.name.strip(), body.kind, body.budget or None, body.id))
            else:
                c.execute("INSERT INTO categories (name, kind, budget, position) VALUES (?,?,?,1000)",
                          (body.name.strip(), body.kind, body.budget or None))
        except Exception:                                       # noqa: BLE001
            raise HTTPException(409, "Ce nom de catégorie existe déjà")
    return {"ok": True}


@router.post("/categories/delete")
async def delete_category(body: IdIn):
    """Les opérations concernées repassent par la catégorisation automatique."""
    with db.connect() as c:
        c.execute("UPDATE operations SET category_id = NULL, category_locked = 0 WHERE category_id = ?", (body.id,))
        c.execute("DELETE FROM categories WHERE id = ?", (body.id,))
        sync.categorize_pending(c)
    return {"ok": True}


@router.post("/rules/delete")
async def delete_rule(body: IdIn):
    with db.connect() as c:
        c.execute("DELETE FROM rules WHERE id = ?", (body.id,))
    return {"ok": True}
