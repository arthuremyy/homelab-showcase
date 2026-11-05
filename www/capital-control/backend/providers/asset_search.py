"""
Provider: Recherche d'actifs par ISIN ou nom.
Combine Yahoo Finance Search + OpenFIGI + CoinGecko.
Détermine l'éligibilité PEA selon l'exchange et le type d'instrument.
"""
import asyncio
import logging
import re

import httpx

logger = logging.getLogger("capital.asset_search")

YF_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
COINGECKO_SEARCH_URL = "https://api.coingecko.com/api/v3/search"

# Exchanges Euronext Paris → PEA éligible
PEA_EXCHANGES = {"PAR", "EPA", "XPAR", "ENX", "PA"}

_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")


def _looks_like_isin(q: str) -> bool:
    return bool(_ISIN_RE.match(q.upper()))


def _is_pea_eligible(exchange: str, quote_type: str) -> bool:
    """
    Éligibilité PEA :
    - Instrument listé sur Euronext Paris (exchange PAR/EPA/XPAR)
    - ET c'est un ETF (UCITS) ou une action (EQUITY) d'une société UE
    - Les cryptos et instruments US sont toujours non-éligibles
    """
    if not exchange:
        return False
    exchange_up = exchange.upper()
    if any(e in exchange_up for e in PEA_EXCHANGES):
        return quote_type in ("ETF", "EQUITY", "MUTUALFUND")
    return False


def _map_quote_type(qt: str) -> str:
    mapping = {
        "ETF": "etf",
        "EQUITY": "stock",
        "MUTUALFUND": "etf",
        "CRYPTOCURRENCY": "crypto",
        "INDEX": "index",
        "CURRENCY": "currency",
        "FUTURE": "future",
        "OPTION": "option",
    }
    return mapping.get(qt, "stock")


async def _search_yahoo(query: str) -> list[dict]:
    """Recherche via Yahoo Finance /v1/finance/search."""
    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            resp = await client.get(YF_SEARCH_URL, params={
                "q": query,
                "quotesCount": 10,
                "newsCount": 0,
                "enableFuzzyQuery": True,
                "region": "FR",
                "lang": "fr-FR",
            })
            resp.raise_for_status()
            quotes = resp.json().get("quotes", [])
    except Exception as e:
        logger.warning(f"Yahoo search error: {e}")
        return []

    results = []
    for q in quotes:
        qt = q.get("quoteType", "EQUITY")
        exchange = q.get("exchange", "")
        ticker = q.get("symbol", "")
        if not ticker:
            continue
        # Tenter d'extraire l'ISIN depuis les résultats (pas toujours dispo)
        isin = None
        results.append({
            "isin": isin,
            "name": q.get("longname") or q.get("shortname") or ticker,
            "ticker": ticker,
            "asset_type": _map_quote_type(qt),
            "exchange": exchange,
            "currency": q.get("currency", "EUR"),
            "pea_eligible": _is_pea_eligible(exchange, qt),
            "coingecko_id": None,
        })
    return results[:8]


async def _search_coingecko(query: str) -> list[dict]:
    """Recherche crypto via CoinGecko."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(COINGECKO_SEARCH_URL, params={"query": query})
            resp.raise_for_status()
            coins = resp.json().get("coins", [])
    except Exception as e:
        logger.warning(f"CoinGecko search error: {e}")
        return []

    results = []
    for c in coins[:4]:
        results.append({
            "isin": f"CRYPTO-{c['id'].upper()}",
            "name": c.get("name", c["id"]),
            "ticker": c.get("symbol", "").upper(),
            "asset_type": "crypto",
            "exchange": "CRYPTO",
            "currency": "EUR",
            "pea_eligible": False,
            "coingecko_id": c["id"],
        })
    return results


async def _resolve_isin(isin: str) -> list[dict]:
    """
    Résolution ISIN via OpenFIGI + Yahoo Finance Search.
    OpenFIGI donne le MIC (exchange), Yahoo donne le ticker.
    """
    isin_up = isin.upper()
    figi_task = _figi_lookup(isin_up)
    yahoo_task = _search_yahoo(isin_up)
    figi_results, yahoo_results = await asyncio.gather(figi_task, yahoo_task, return_exceptions=True)

    # Construire un index exchange par ticker depuis FIGI
    figi_exchanges: dict[str, str] = {}
    if isinstance(figi_results, list):
        for f in figi_results:
            if f.get("ticker") and f.get("exchange"):
                figi_exchanges[f["ticker"]] = f["exchange"]

    # Enrichir les résultats Yahoo avec ISIN et exchange FIGI si dispo
    enriched = []
    yahoo_list = yahoo_results if isinstance(yahoo_results, list) else []
    for r in yahoo_list:
        r["isin"] = isin_up
        # Si FIGI a un exchange pour ce ticker, l'utiliser (plus fiable)
        if r["ticker"] in figi_exchanges:
            r["exchange"] = figi_exchanges[r["ticker"]]
        r["pea_eligible"] = _is_pea_eligible(r["exchange"], r["asset_type"].upper())
        enriched.append(r)

    # Si Yahoo n'a rien trouvé mais FIGI oui, construire depuis FIGI
    if not enriched and isinstance(figi_results, list):
        for f in figi_results:
            enriched.append({
                "isin": isin_up,
                "name": f.get("name", isin_up),
                "ticker": f.get("ticker"),
                "asset_type": f.get("asset_type", "stock"),
                "exchange": f.get("exchange", ""),
                "currency": "EUR",
                "pea_eligible": _is_pea_eligible(f.get("exchange", ""), f.get("asset_type", "EQUITY")),
                "coingecko_id": None,
            })

    return enriched


async def _figi_lookup(isin: str) -> list[dict]:
    """Appel OpenFIGI pour résoudre ISIN → MIC + type."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                OPENFIGI_URL,
                json=[{"idType": "ID_ISIN", "idValue": isin}],
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"OpenFIGI error for {isin}: {e}")
        return []

    results = []
    for item in data:
        for fig in item.get("data", []):
            exch_code = fig.get("exchCode", "")
            security_type = fig.get("securityType", "")
            ticker = fig.get("ticker", "")
            name = fig.get("name", "")
            asset_type = "etf" if "ETF" in security_type.upper() else "stock"
            # exchCode from FIGI: "XPAR" = Paris, "XAMS" = Amsterdam, etc.
            results.append({
                "ticker": ticker,
                "name": name,
                "exchange": exch_code,
                "asset_type": asset_type,
            })
    return results


async def search_assets(query: str) -> list[dict]:
    """
    Point d'entrée principal.
    - Si ISIN (12 chars) → OpenFIGI + Yahoo en parallèle
    - Sinon → Yahoo Search + CoinGecko Search en parallèle
    Retourne une liste dédupliquée avec schéma unifié.
    """
    query = query.strip()

    if _looks_like_isin(query):
        results = await _resolve_isin(query)
    else:
        yahoo_task = _search_yahoo(query)
        cg_task = _search_coingecko(query)
        yahoo_results, cg_results = await asyncio.gather(yahoo_task, cg_task, return_exceptions=True)
        results = []
        if isinstance(yahoo_results, list):
            results.extend(yahoo_results)
        if isinstance(cg_results, list):
            results.extend(cg_results)

    # Déduplique par ticker
    seen: set[str] = set()
    deduped = []
    for r in results:
        key = r.get("ticker") or r.get("isin") or r.get("name")
        if key and key not in seen:
            seen.add(key)
            deduped.append(r)

    return deduped
