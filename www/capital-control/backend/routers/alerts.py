"""Alertes de prix — règles simples (seuil, variation du jour) et journal des déclenchements."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import db

router = APIRouter(prefix="/api")

KINDS = {"price_above", "price_below", "pct_day"}


class RuleIn(BaseModel):
    isin: str = Field(min_length=1)
    kind: str
    threshold: float
    cooldown_h: int = Field(default=24, ge=1, le=720)

    @field_validator("kind")
    @classmethod
    def _kind_ok(cls, v):
        if v not in KINDS:
            raise ValueError(f"kind doit être parmi {sorted(KINDS)}")
        return v


@router.get("/alerts/rules")
async def list_rules():
    with db.connect() as conn:
        rules = db.rows(conn.execute("""
            SELECT r.*, a.name AS asset_name FROM alert_rules r
            LEFT JOIN asset_registry a ON a.isin = r.isin
            ORDER BY r.id DESC
        """))
    return {"status": "ok", "rules": rules}


@router.post("/alerts/rules")
async def create_rule(rule: RuleIn):
    if not db.get_asset(rule.isin):
        return JSONResponse(status_code=404, content={"error": f"Actif {rule.isin} inconnu"})
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO alert_rules (isin, kind, threshold, cooldown_h) VALUES (?, ?, ?, ?)",
            (rule.isin, rule.kind, rule.threshold, rule.cooldown_h))
        conn.commit()
        return {"status": "ok", "id": cur.lastrowid}


@router.delete("/alerts/rules/{rule_id}")
async def delete_rule(rule_id: int):
    with db.connect() as conn:
        conn.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
        conn.commit()
    return {"status": "ok"}


@router.post("/alerts/rules/{rule_id}/toggle")
async def toggle_rule(rule_id: int):
    with db.connect() as conn:
        conn.execute("UPDATE alert_rules SET enabled = 1 - enabled WHERE id = ?", (rule_id,))
        conn.commit()
        r = conn.execute("SELECT enabled FROM alert_rules WHERE id = ?", (rule_id,)).fetchone()
    if not r:
        return JSONResponse(status_code=404, content={"error": "Règle introuvable"})
    return {"status": "ok", "enabled": bool(r["enabled"])}


@router.get("/alerts/events")
async def list_events(all: bool = False, limit: int = 50):
    with db.connect() as conn:
        if all:
            events = db.rows(conn.execute(
                "SELECT * FROM alert_events ORDER BY id DESC LIMIT ?", (limit,)))
        else:
            events = db.rows(conn.execute(
                "SELECT * FROM alert_events WHERE read = 0 ORDER BY id DESC LIMIT ?", (limit,)))
    return {"status": "ok", "events": events}


@router.post("/alerts/events/read")
async def mark_events_read():
    with db.connect() as conn:
        conn.execute("UPDATE alert_events SET read = 1 WHERE read = 0")
        conn.commit()
    return {"status": "ok"}
