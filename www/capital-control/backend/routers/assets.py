"""Registre d'actifs et recherche."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import db
from providers.asset_search import search_assets
from services.pricing import update_all_prices

logger = logging.getLogger("capital.assets")
router = APIRouter(prefix="/api")


class AssetIn(BaseModel):
    isin: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    ticker: str = ""
    asset_type: str = "stock"
    exchange: str = ""
    currency: str = "EUR"
    pea_eligible: bool = False
    coingecko_id: str = ""
    news_query: str = ""

    # La recherche renvoie null pour les champs absents (coingecko_id des actions et ETF)
    @field_validator("ticker", "exchange", "coingecko_id", "news_query", mode="before")
    @classmethod
    def _null_vide(cls, v):
        return "" if v is None else v


class AssetPatch(BaseModel):
    news_query: str | None = None
    asset_class: str | None = None
    name: str | None = None


@router.get("/assets/search")
async def search_asset_endpoint(q: str = ""):
    if not q or len(q.strip()) < 2:
        return JSONResponse(status_code=400, content={"error": "Query trop courte (min 2 chars)"})
    try:
        results = await search_assets(q.strip())
        for r in results:
            r["news_query"] = db._guess_news_query(r.get("name", ""), r.get("asset_type", "stock"))
        return {"status": "ok", "results": results}
    except Exception as e:
        logger.error(f"Asset search error: {e}")
        return JSONResponse(status_code=502, content={"error": str(e)})


@router.get("/assets")
async def list_assets():
    return {"status": "ok", "assets": db.get_all_assets()}


@router.post("/assets")
async def register_asset(asset: AssetIn):
    with db.connect() as conn:
        conn.execute("""
            INSERT INTO asset_registry
                (isin, name, ticker, asset_type, exchange, currency, pea_eligible,
                 coingecko_id, news_query, asset_class)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(isin) DO UPDATE SET
                name=excluded.name, ticker=excluded.ticker, asset_type=excluded.asset_type,
                exchange=excluded.exchange, currency=excluded.currency,
                pea_eligible=excluded.pea_eligible, coingecko_id=excluded.coingecko_id
        """, (asset.isin, asset.name, asset.ticker, asset.asset_type, asset.exchange,
              asset.currency, 1 if asset.pea_eligible else 0, asset.coingecko_id,
              asset.news_query or db._guess_news_query(asset.name, asset.asset_type),
              db._guess_asset_class(asset.name, asset.asset_type)))
        conn.commit()
    await update_all_prices()
    return {"status": "ok", "message": f"Actif {asset.name} ({asset.isin}) enregistré"}


@router.patch("/assets/{isin}")
async def patch_asset(isin: str, patch: AssetPatch):
    fields, params = [], []
    for col in ("news_query", "asset_class", "name"):
        val = getattr(patch, col)
        if val is not None:
            fields.append(f"{col} = ?")
            params.append(val)
    if not fields:
        return JSONResponse(status_code=400, content={"error": "Rien à modifier"})
    params.append(isin)
    with db.connect() as conn:
        cur = conn.execute(f"UPDATE asset_registry SET {', '.join(fields)} WHERE isin = ?", params)
        conn.commit()
        if cur.rowcount == 0:
            return JSONResponse(status_code=404, content={"error": f"Actif {isin} introuvable"})
    return {"status": "ok"}


@router.delete("/assets/{isin}")
async def remove_asset(isin: str):
    with db.connect() as conn:
        has_tx = conn.execute("SELECT COUNT(*) c FROM transactions WHERE isin = ?",
                              (isin,)).fetchone()["c"]
        if has_tx:
            return JSONResponse(status_code=409, content={
                "error": f"{has_tx} transaction(s) référencent cet actif — supprimez-les d'abord "
                         "ou gardez l'actif pour l'historique."})
        conn.execute("DELETE FROM asset_registry WHERE isin = ?", (isin,))
        conn.execute("DELETE FROM prices_last WHERE isin = ?", (isin,))
        conn.commit()
    return {"status": "ok", "message": f"Actif {isin} supprimé du registre"}
