"""Provider: Données de marché (CoinGecko) — Prix BTC temps réel + historique."""
import asyncio
import logging
import time
import httpx

logger = logging.getLogger("capital.market")

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
CG_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# ── Cache in-memory ─────────────────────────────────────────────────────────
_cache: dict[str, dict] = {}
_locks: dict[str, asyncio.Lock] = {}

CACHE_TTL_PRICES  = 60     # secondes
CACHE_TTL_HISTORY = 600    # 10 min — évite le rate-limit CoinGecko


def _cache_get(key: str) -> dict | None:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry["ts"] < entry["ttl"]:
        return entry["data"]
    return None


def _cache_set(key: str, data: dict, ttl: int) -> None:
    _cache[key] = {"data": data, "ts": time.monotonic(), "ttl": ttl}


def _get_lock(key: str) -> asyncio.Lock:
    """Retourne le lock associé à une clé (déduplique les requêtes en vol)."""
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


# ── CoinGecko API ─────────────────────────────────────────────────────────────

async def _cg_get(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    """GET CoinGecko avec retry exponentiel sur 429."""
    for attempt in range(4):
        resp = await client.get(url, params=params)
        if resp.status_code == 429:
            wait = 2 ** attempt          # 1s, 2s, 4s, 8s
            logger.warning("CoinGecko 429 — attente %ds (tentative %d)", wait, attempt + 1)
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # lève l'erreur si toutes les tentatives échouent


async def get_crypto_prices(ids: list[str], vs: str = "eur") -> dict:
    """Prix actuels depuis CoinGecko."""
    key = f"prices:{','.join(sorted(ids))}:{vs}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    async with _get_lock(key):
        cached = _cache_get(key)
        if cached is not None:
            return cached

        async with httpx.AsyncClient(timeout=20, headers=CG_HEADERS) as client:
            data = await _cg_get(client, f"{COINGECKO_BASE}/simple/price", {
                "ids": ",".join(ids),
                "vs_currencies": vs,
                "include_24hr_change": "true",
                "include_market_cap": "true",
            })

    _cache_set(key, data, CACHE_TTL_PRICES)
    return data


async def get_crypto_history(coin_id: str, days: int = 90, vs: str = "eur") -> dict:
    """
    Historique de prix pour graphiques et indicateurs.

    Granularité CoinGecko free tier :
      days=1       → 5 min  (~288 pts)
      days=2-90    → 1h     (~168-2160 pts)
      days=91-365  → 1j     (91-365 pts)
    """
    days = min(days, 365)
    key = f"history:{coin_id}:{days}:{vs}"

    cached = _cache_get(key)
    if cached is not None:
        return cached

    # Déduplique les appels simultanés pour la même clé
    async with _get_lock(key):
        cached = _cache_get(key)
        if cached is not None:
            return cached

        async with httpx.AsyncClient(timeout=30, headers=CG_HEADERS) as client:
            data = await _cg_get(
                client,
                f"{COINGECKO_BASE}/coins/{coin_id}/market_chart",
                {"vs_currency": vs, "days": days},
            )

        # Injecter le prix temps réel comme dernier point
        try:
            price_data = await get_crypto_prices([coin_id], vs)
            current_price = price_data.get(coin_id, {}).get(vs)
            if current_price and data.get("prices"):
                now_ms = int(time.time() * 1000)
                data["prices"].append([now_ms, current_price])
        except Exception:
            pass

        _cache_set(key, data, CACHE_TTL_HISTORY)

    return data
