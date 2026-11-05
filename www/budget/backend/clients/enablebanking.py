"""
Client Enable Banking (agrégateur DSP2) — https://enablebanking.com/docs/api/reference/

Mode « restricted » gratuit : l'application ne lit QUE les comptes reliés au
préalable dans la console Enable Banking. Authentification : JWT RS256 signé
par la clé privée de l'application (`kid` = identifiant de l'application).

Limites DSP2 à connaître :
  - 4 lectures par jour et par compte quand l'utilisateur n'est pas présent ;
    une synchronisation déclenchée depuis l'interface envoie les en-têtes
    Psu-* et ne compte pas dans ce quota ;
  - consentement limité (180 jours chez la plupart des banques), à renouveler.
"""
import logging
import time
from pathlib import Path

import httpx
import jwt

from config import settings

logger = logging.getLogger("budget.eb")

BASE = "https://api.enablebanking.com"
TOKEN_TTL = 3600


class EBError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"Enable Banking HTTP {status} : {detail}")
        self.status = status
        self.detail = detail


def configured() -> bool:
    return bool(settings.eb_app_id) and Path(settings.eb_key_path).is_file()


def _token() -> str:
    key = Path(settings.eb_key_path).read_text()
    now = int(time.time())
    return jwt.encode({"iss": "enablebanking.com", "aud": "api.enablebanking.com",
                       "iat": now, "exp": now + TOKEN_TTL},
                      key, algorithm="RS256", headers={"kid": settings.eb_app_id})


async def _call(method: str, path: str, *, json=None, params=None, psu: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    if psu:
        headers.update(psu)
    async with httpx.AsyncClient(base_url=BASE, timeout=httpx.Timeout(90, connect=15)) as c:
        r = await c.request(method, path, json=json, params=params, headers=headers)
    if r.status_code >= 400:
        try:
            detail = r.json().get("message") or r.text
        except ValueError:
            detail = r.text
        raise EBError(r.status_code, str(detail)[:300])
    return r.json() if r.content else {}


# ── Consentement ────────────────────────────────────────────────────────────

async def find_aspsp() -> dict:
    """Banque cible (EB_ASPSP), comparée sans accents ni casse."""
    from services.categorize import normalize
    data = await _call("GET", "/aspsps", params={"country": settings.eb_country})
    want = normalize(settings.eb_aspsp)
    for a in data.get("aspsps", []):
        if normalize(a.get("name", "")) == want:
            return a
    raise EBError(404, f"banque « {settings.eb_aspsp} » introuvable chez Enable Banking")


async def start_auth(state: str, days: int = 180) -> dict:
    """Démarre le consentement, pour la durée maximale acceptée par la banque."""
    from datetime import datetime, timedelta, timezone
    a = await find_aspsp()
    secs = min(days * 86400, int(a.get("maximum_consent_validity") or days * 86400))
    valid_until = (datetime.now(timezone.utc) + timedelta(seconds=secs - 60)).isoformat(timespec="seconds")
    return await _call("POST", "/auth", json={
        "access": {"valid_until": valid_until},
        "aspsp": {"name": a["name"], "country": a["country"]},
        "state": state,
        "redirect_url": settings.eb_redirect_url,
        "psu_type": "personal",
    })


async def create_session(code: str) -> dict:
    return await _call("POST", "/sessions", json={"code": code})


async def get_session(session_id: str) -> dict:
    return await _call("GET", f"/sessions/{session_id}")


async def delete_session(session_id: str) -> None:
    await _call("DELETE", f"/sessions/{session_id}")


# ── Données ─────────────────────────────────────────────────────────────────

async def balances(uid: str, psu: dict | None = None) -> list[dict]:
    return (await _call("GET", f"/accounts/{uid}/balances", psu=psu)).get("balances", [])


async def transactions(uid: str, date_from: str, psu: dict | None = None) -> list[dict]:
    """Toutes les pages depuis `date_from` (comptabilisées ET en attente)."""
    out, key = [], None
    for _ in range(50):
        params = {"date_from": date_from}
        if key:
            params["continuation_key"] = key
        page = await _call("GET", f"/accounts/{uid}/transactions", params=params, psu=psu)
        out.extend(page.get("transactions", []))
        key = page.get("continuation_key")
        if not key:
            break
    return out
