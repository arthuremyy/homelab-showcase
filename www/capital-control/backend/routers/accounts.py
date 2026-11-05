"""Comptes, pointages et import des avis Natixis (PEE)."""
import json
import logging
from datetime import date, timedelta

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import db
from services import checks, history, natixis, valuation

logger = logging.getLogger("capital.accounts")
router = APIRouter(prefix="/api")


def _account_or_404(account_id: str):
    if account_id not in db.ACCOUNT_IDS:
        return JSONResponse(status_code=404, content={"error": f"Compte {account_id} inconnu"})
    return None


@router.get("/accounts/{account_id}")
async def account_detail(account_id: str):
    if err := _account_or_404(account_id):
        return err
    summary = valuation.portfolio_summary()
    acc = next(a for a in summary["accounts"] if a["id"] == account_id)
    positions = [p for p in summary["positions"] if p["account"] == account_id]
    out = {"status": "ok", "account": acc, "positions": positions}
    if account_id == "PEA":
        out["pea"] = valuation.pea_status()
    if account_id == "PEE":
        lots: dict[str, float] = {}
        for p in positions:
            for lot in p["lots"]:
                k = lot["available_on"] or "inconnue"
                lots[k] = round(lots.get(k, 0) + lot["value"], 2)
        out["availability"] = [{"available_on": k, "value": v} for k, v in sorted(lots.items())]
    return out


@router.get("/accounts/{account_id}/checks")
async def account_checks(account_id: str):
    if err := _account_or_404(account_id):
        return err
    with db.connect() as conn:
        rows = db.rows(conn.execute(
            "SELECT * FROM checks WHERE account = ? ORDER BY date DESC, id DESC LIMIT 24", (account_id,)))
    for r in rows:
        r["lines"] = json.loads(r["lines"] or "[]")
    return {"status": "ok", "checks": rows}


# ── Pointage manuel ──

class DeclaredLine(BaseModel):
    isin: str = Field(min_length=1, max_length=40)
    shares: float = Field(ge=0)
    value: float | None = Field(default=None, ge=0)


class CheckIn(BaseModel):
    lines: list[DeclaredLine]
    cash: float | None = Field(default=None, ge=0)
    date: str = Field(default_factory=lambda: date.today().isoformat())
    adjust: bool = False             # créer les mouvements de rattrapage

    @field_validator("date")
    @classmethod
    def _date_ok(cls, v):
        if date.fromisoformat(v[:10]) > date.today():
            raise ValueError("date future")
        return v[:10]


@router.post("/accounts/{account_id}/check/preview")
async def check_preview(account_id: str, body: CheckIn):
    if err := _account_or_404(account_id):
        return err
    return {"status": "ok", **checks.evaluate(account_id, body.date,
                                               [l.model_dump() for l in body.lines], body.cash)}


@router.post("/accounts/{account_id}/check")
async def check_commit(account_id: str, body: CheckIn):
    if err := _account_or_404(account_id):
        return err
    result = checks.evaluate(account_id, body.date, [l.model_dump() for l in body.lines], body.cash)
    saved = checks.commit(result, body.adjust)
    if saved["adjustments"]:
        history.schedule_rebuild()
    return {"status": "ok", **saved}


# ── PEE : avis d'opération Natixis ──

def _pee_assets() -> dict[str, dict]:
    return {natixis.norm(a["name"]): a for a in db.get_all_assets()}


def _resolve_fund(fund: str, known: dict[str, dict]) -> tuple[str | None, str | None]:
    """Nom lu dans l'avis → (isin, nom). Repli sur le catalogue des fonds du plan."""
    if fund in known:
        return known[fund]["isin"], known[fund]["name"]
    if fund in natixis.CATALOGUE:
        return natixis.CATALOGUE[fund][0], fund.title()
    return None, None


def _read_avis(data: bytes) -> dict:
    parsed = natixis.parse(natixis.pdf_text(data))
    known = _pee_assets()
    unknown = set()
    for item in parsed["operations"] + parsed["lots"]:
        item["isin"], item["name"] = _resolve_fund(item["fund"], known)
        if not item["isin"]:
            unknown.add(item["fund"])
    with db.connect() as conn:
        for op in parsed["operations"]:
            op["external_id"] = f"natixis:{op['date']}:{op['isin']}:{op['shares']}"
            op["exists"] = bool(conn.execute("SELECT 1 FROM transactions WHERE external_id = ?",
                                             (op["external_id"],)).fetchone())
    parsed["unknown_funds"] = sorted(unknown)
    return parsed


async def _our_prices(lots: list[dict]) -> dict[str, float]:
    """Notre cours de chaque fonds à la date de valorisation de l'avis (contrôle de la source de prix).
    Sans historique (fonds sans ticker), la valeur de part de l'avis fait foi."""
    out = {}
    for lot in lots:
        if lot["isin"] in out:
            continue
        out[lot["isin"]] = lot["price"]
        asset = db.get_asset(lot["isin"])
        if asset and asset.get("ticker"):
            start = (date.fromisoformat(lot["date"]) - timedelta(days=10)).isoformat()
            closes = await history.closes_for(asset, start)
            before = [d for d in closes if d <= lot["date"]]
            if before:
                out[lot["isin"]] = closes[max(before)]
    return out


async def _avis_check(parsed: dict, extra_ops: list[dict]) -> dict | None:
    """Pointage à la date de situation : parts par fonds et par date de disponibilité.
    `extra_ops` : versements de l'avis pas encore enregistrés, comptés comme s'ils l'étaient."""
    if not parsed["lots"] or not parsed["situation_date"]:
        return None
    declared: dict[str, dict] = {}
    for lot in parsed["lots"]:
        d = declared.setdefault(lot["isin"], {"isin": lot["isin"], "shares": 0.0, "value": 0.0, "lots": {},
                                              "price": lot["price"]})
        d["shares"] = round(d["shares"] + lot["shares"], 6)
        d["value"] = round(d["value"] + lot["value"], 2)
        d["lots"][lot["available_on"]] = round(d["lots"].get(lot["available_on"], 0) + lot["shares"], 6)
    prices = await _our_prices(parsed["lots"])
    result = checks.evaluate("PEE", parsed["situation_date"], list(declared.values()), None, prices)
    # Les versements non encore saisis comptent dans le calcul (aperçu avant import).
    for op in extra_ops:
        for l in result["lines"]:
            if l["isin"] == op["isin"]:
                l["computed_shares"] = round(l["computed_shares"] + op["shares"], 8)
                l["share_gap"] = round(l["declared_shares"] - l["computed_shares"], 8)
                l["share_ok"] = abs(l["share_gap"]) <= checks.SHARE_TOL_DEFAULT
                for x in l.get("lots", []):
                    if x["available_on"] == op["available_on"]:
                        x["computed_shares"] = round(x["computed_shares"] + op["shares"], 6)
                        x["ok"] = abs(x["declared_shares"] - x["computed_shares"]) <= checks.SHARE_TOL_DEFAULT
                l["computed_value"] = round(l["computed_shares"] * (l["our_price"] or 0), 2)
    result["computed_total"] = round(sum(l["computed_value"] for l in result["lines"]), 2)
    result["share_gaps"] = sum(1 for l in result["lines"] if not l["share_ok"])
    result["status"] = "ok" if all(l["share_ok"] and l["price_ok"] for l in result["lines"]) else "ecart"
    return result


async def _upload(file: UploadFile) -> bytes | JSONResponse:
    data = await file.read()
    if len(data) > 5_000_000 or not data.startswith(b"%PDF"):
        return JSONResponse(status_code=400, content={"error": "Fichier PDF attendu (5 Mo maximum)"})
    return data


@router.post("/pee/import/preview")
async def pee_import_preview(file: UploadFile = File(...)):
    data = await _upload(file)
    if isinstance(data, JSONResponse):
        return data
    try:
        parsed = _read_avis(data)
    except Exception as e:
        logger.warning(f"Avis Natixis illisible : {e}")
        return JSONResponse(status_code=400, content={"error": "PDF illisible"})
    if not parsed["operations"] and not parsed["lots"]:
        return JSONResponse(status_code=400, content={
            "error": "Aucun versement ni situation des avoirs reconnus dans ce PDF"})
    new_ops = [op for op in parsed["operations"] if not op["exists"] and op["isin"]]
    return {"status": "ok", **parsed, "check": await _avis_check(parsed, new_ops)}


@router.post("/pee/import")
async def pee_import(file: UploadFile = File(...), adjust: bool = Form(False)):
    """Enregistre les versements de l'avis (sans doublon), puis le pointage de la situation ;
    avec `adjust`, rattrape les écarts restants."""
    data = await _upload(file)
    if isinstance(data, JSONResponse):
        return data
    parsed = _read_avis(data)
    if parsed["unknown_funds"]:
        return JSONResponse(status_code=400, content={
            "error": "Fonds inconnus : " + ", ".join(parsed["unknown_funds"])})
    added = 0
    with db.connect() as conn:
        for op in parsed["operations"]:
            if op["exists"]:
                continue
            if not conn.execute("SELECT 1 FROM asset_registry WHERE isin = ?", (op["isin"],)).fetchone():
                cls = natixis.CATALOGUE.get(op["fund"], (None, "mixed"))[1]
                conn.execute("""INSERT INTO asset_registry (isin, name, asset_type, asset_class, currency)
                                VALUES (?, ?, 'fund', ?, 'EUR')""", (op["isin"], op["name"], cls))
                conn.execute("""INSERT OR IGNORE INTO prices_last (isin, price, currency, price_eur, change_24h, updated_at)
                                VALUES (?, ?, 'EUR', ?, 0, ?)""", (op["isin"], op["price"], op["price"], op["date"]))
            conn.execute("""
                INSERT INTO transactions (date, type, isin, name, shares, price, amount, fees, account, broker,
                                          note, source, employer_amount, social_tax, available_on, external_id)
                VALUES (?, 'buy', ?, ?, ?, ?, ?, 0, 'PEE', 'Natixis Interépargne', ?, 'pdf', ?, ?, ?, ?)
            """, (op["date"], op["isin"], op["name"], op["shares"], op["price"], op["amount"],
                  parsed["category"], op["employer_amount"], op["social_tax"], op["available_on"],
                  op["external_id"]))
            added += 1
        conn.commit()
    saved = None
    if check := await _avis_check(parsed, []):
        saved = checks.commit(check, adjust, source="pdf")
    if added or (saved and saved["adjustments"]):
        history.schedule_rebuild()
    return {"status": "ok", "added": added, "check": saved}
