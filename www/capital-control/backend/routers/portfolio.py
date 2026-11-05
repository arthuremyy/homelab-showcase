"""Portefeuille — résumé (lu aussi par Budget), historique, rafraîchissement des prix."""
from fastapi import APIRouter

from services import history, pricing, valuation

router = APIRouter(prefix="/api")


@router.get("/portfolio")
async def get_portfolio():
    return {"status": "ok", **valuation.portfolio_summary()}


@router.get("/portfolio/history")
async def portfolio_history(range: str = "max"):
    return {"status": "ok", "range": range, "history": history.get_history(range),
            "variations": {"30d": history.variation(30)}}


@router.post("/portfolio/refresh")
async def refresh_prices():
    updated = await pricing.update_all_prices(include_stocks=True)
    return {"status": "ok", "updated": updated, **valuation.portfolio_summary()}
