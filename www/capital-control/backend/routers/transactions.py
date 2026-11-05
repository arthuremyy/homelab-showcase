"""Mouvements — la source de vérité du portefeuille. Création, modification, suppression, export."""
import csv
import io
from datetime import date

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator

import db
from services import history, valuation

router = APIRouter(prefix="/api")

TX_TYPES = {"buy", "sell", "dividend", "fee"}
COLUMNS = ("date", "type", "isin", "name", "shares", "price", "amount", "fees", "employer_amount",
           "social_tax", "available_on", "account", "source", "note")


class TransactionIn(BaseModel):
    type: str
    account: str
    date: str = Field(default_factory=lambda: date.today().isoformat())
    isin: str = Field(min_length=1, max_length=40)
    shares: float = Field(default=0, ge=0)
    price: float = Field(default=0, ge=0)
    amount: float = Field(default=0, ge=0)        # 0 pour un achat/vente → parts × prix
    fees: float = Field(default=0, ge=0)
    employer_amount: float = Field(default=0, ge=0)
    social_tax: float = Field(default=0, ge=0)
    available_on: str | None = None
    note: str = Field(default="", max_length=300)

    @field_validator("type")
    @classmethod
    def _type_ok(cls, v):
        if v not in TX_TYPES:
            raise ValueError(f"type parmi {sorted(TX_TYPES)}")
        return v

    @field_validator("account")
    @classmethod
    def _account_ok(cls, v):
        if v not in db.ACCOUNT_IDS:
            raise ValueError(f"compte parmi {sorted(db.ACCOUNT_IDS)}")
        return v

    @field_validator("date", "available_on")
    @classmethod
    def _date_ok(cls, v):
        if v in (None, ""):
            return None
        date.fromisoformat(v[:10])
        return v[:10]


def _validate(tx: TransactionIn, exclude_id: int | None = None) -> tuple[dict | None, JSONResponse | None]:
    asset = db.get_asset(tx.isin)
    if not asset:
        return None, JSONResponse(status_code=400, content={"error": f"Actif {tx.isin} inconnu"})
    if tx.date > date.today().isoformat():
        return None, JSONResponse(status_code=400, content={"error": "Date dans le futur"})
    row = tx.model_dump()
    row["name"] = asset["name"]
    if tx.type in ("buy", "sell"):
        if tx.shares <= 0:
            return None, JSONResponse(status_code=400, content={"error": "Quantité requise"})
        if not tx.amount:
            if not tx.price:
                return None, JSONResponse(status_code=400, content={"error": "Prix ou montant requis"})
            row["amount"] = round(tx.shares * tx.price, 2)
        if not tx.price:
            row["price"] = round(row["amount"] / tx.shares, 6)
    elif tx.amount <= 0:
        return None, JSONResponse(status_code=400, content={"error": "Montant requis"})
    if tx.type == "sell":
        others = [t for t in db.get_transactions(tx.account) if t["isin"] == tx.isin and t["id"] != exclude_id]
        held = valuation.replay(others, tx.date)["shares"]
        if tx.shares > held + 1e-9:
            return None, JSONResponse(status_code=400, content={
                "error": f"Vente impossible : {tx.shares:g} parts, {held:g} détenues à cette date"})
    return row, None


@router.get("/transactions")
async def list_transactions(account: str | None = None):
    return {"status": "ok", "transactions": db.get_transactions(account)}


@router.post("/transactions")
async def add_transaction(tx: TransactionIn):
    row, err = _validate(tx)
    if err:
        return err
    with db.connect() as conn:
        provider = conn.execute("SELECT provider FROM accounts WHERE id = ?", (tx.account,)).fetchone()[0]
        cur = conn.execute("""
            INSERT INTO transactions (date, type, isin, name, shares, price, amount, fees, employer_amount,
                                      social_tax, available_on, account, broker, note, source)
            VALUES (:date, :type, :isin, :name, :shares, :price, :amount, :fees, :employer_amount,
                    :social_tax, :available_on, :account, :broker, :note, 'manuel')
        """, {**row, "broker": provider})
        conn.commit()
    history.schedule_rebuild()
    return {"status": "ok", "id": cur.lastrowid}


@router.put("/transactions/{tx_id}")
async def update_transaction(tx_id: int, tx: TransactionIn):
    row, err = _validate(tx, exclude_id=tx_id)
    if err:
        return err
    with db.connect() as conn:
        cur = conn.execute("""
            UPDATE transactions SET date = :date, type = :type, isin = :isin, name = :name, shares = :shares,
                   price = :price, amount = :amount, fees = :fees, employer_amount = :employer_amount,
                   social_tax = :social_tax, available_on = :available_on, account = :account, note = :note
            WHERE id = :id
        """, {**row, "id": tx_id})
        conn.commit()
    if not cur.rowcount:
        return JSONResponse(status_code=404, content={"error": "Mouvement introuvable"})
    history.schedule_rebuild()
    return {"status": "ok"}


@router.delete("/transactions/{tx_id}")
async def delete_transaction(tx_id: int):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Mouvement introuvable"})
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        conn.commit()
    history.schedule_rebuild()
    return {"status": "ok", "deleted": dict(row)}


@router.get("/export")
async def export_csv():
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(COLUMNS)
    for t in db.get_transactions():
        writer.writerow([t.get(c) if t.get(c) is not None else "" for c in COLUMNS])
    return PlainTextResponse(out.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": "attachment; filename=capital_mouvements.csv"})
