"""Réglages et lien vers Capital (investissements)."""
import logging
import time
from datetime import date as date_t

import httpx
import jwt
from fastapi import APIRouter
from pydantic import BaseModel, Field

import db
from config import settings

logger = logging.getLogger("budget.misc")
router = APIRouter(prefix="/api/budget")

_capital_cache: dict = {"at": 0.0, "data": None}
CAPITAL_TTL = 60


class LivretIn(BaseModel):
    amount: float = Field(ge=0, lt=10_000_000)
    date: date_t


class SettingsIn(BaseModel):
    low_balance: float | None = Field(default=None, ge=0, lt=1_000_000)
    livret: LivretIn | None = None


@router.get("/settings")
async def get_settings():
    return db.get_settings()


@router.post("/settings")
async def save_settings(body: SettingsIn):
    db.set_json("settings", {**db.get_settings(), **body.model_dump(mode="json", exclude_none=True)})
    return {"ok": True}


@router.get("/capital")
async def capital():
    """Résumé des investissements, lu chez capital-control (réseau Docker interne)
    avec un jeton de service de 5 minutes. Capital indisponible ⇒ carte masquée."""
    if time.time() - _capital_cache["at"] < CAPITAL_TTL and _capital_cache["data"]:
        return _capital_cache["data"]
    now = int(time.time())
    tok = jwt.encode({"sub": "budget", "iat": now, "exp": now + 300}, settings.jwt_secret, algorithm="HS256")
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{settings.capital_url}/api/portfolio",
                            headers={"Authorization": f"Bearer {tok}"})
        r.raise_for_status()
        p = r.json()
    except Exception as e:                                      # noqa: BLE001
        logger.warning("Capital indisponible : %s", e)
        return {"available": False}
    data = {"available": True,
            **{k: p.get(k) for k in ("total_value", "total_invested", "pnl_eur", "pnl_pct",
                                     "day_change_eur", "day_change_pct", "position_count")}}
    _capital_cache.update(at=time.time(), data=data)
    return data
