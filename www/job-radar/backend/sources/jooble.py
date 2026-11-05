"""
Connecteur Jooble — agrégateur (HelloWork, Free-Work…), REST API partenaire.

    POST https://fr.jooble.org/api/{clé}   corps JSON : keywords, location, radius, page, ResultOnPage

⚠ **Quota : 500 requêtes au total** pour la clé par défaut (courriel Jooble du
2026-10-15 ; plus = demande par courriel). Chaque appel est compté dans
`meta.jooble_calls` et le connecteur s'arrête à `BUDGET` : source quotidienne,
une page par requête, jeu de requêtes court.

Limites : description = extrait (`snippet`), `type` peu fiable (« Stage » sur
des alternances), aucune vérification offre par offre.
"""
import logging
from datetime import datetime, timezone

import httpx

import db
from config import settings
from sources.base import TIMEOUT, dept_from_text, infer_contract, strip_html

logger = logging.getLogger("jobs.jooble")

SEARCH_URL = "https://fr.jooble.org/api/{key}"
RESULTS_PER_PAGE = 100
BUDGET = 480                      # sur 500 : marge pour les tests à la main
META_KEY = "jooble_calls"

TYPE_MAP = {"cdi": "cdi", "cdd": "cdd", "intérim": "interim", "interim": "interim"}


def configured() -> bool:
    return bool(settings.jooble_api_key)


def calls_used() -> int:
    with db.connect() as conn:
        return int(db.get_meta(conn, META_KEY) or 0)


def _count_call():
    with db.connect() as conn:
        db.set_meta(conn, META_KEY, int(db.get_meta(conn, META_KEY) or 0) + 1)
        conn.commit()


def _iso(raw: str) -> str | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:19]).replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def normalize(r: dict) -> dict | None:
    oid = r.get("id")
    title = (r.get("title") or "").strip()
    url = (r.get("link") or "").strip()
    if oid is None or not title or not url:
        return None
    location = (r.get("location") or "").strip()
    description = strip_html(r.get("snippet") or "").strip(" .…")
    # Le titre d'abord : Jooble classe « Stage » des alternances.
    contract = infer_contract(f"{title} {description[:600]}")
    if contract == "unknown":
        contract = TYPE_MAP.get((r.get("type") or "").strip().lower(), "unknown")

    return {
        "source": "jooble",
        "source_id": str(oid),
        "url": url,
        "title": title,
        "company": (r.get("company") or "").strip() or None,
        "location": location or None,
        "dept": dept_from_text(location),
        "remote": "unknown",
        "contract_type": contract,
        "salary_raw": (r.get("salary") or "").strip() or None,   # « 44k € a 48k €/an », lu par parse_salary
        "work_time": (r.get("type") or "").strip() if r.get("type") in ("Temps plein", "Temps partiel") else None,
        "description": description or None,
        "posted_at": _iso(r.get("updated")),
        "_raw": r,
    }


async def fetch(params: dict) -> list[dict]:
    """`params` : {'keywords': str, 'location': str, 'radius': int}."""
    if not configured():
        logger.debug("Jooble non configuré (JOOBLE_API_KEY absent) — ignoré")
        return []
    used = calls_used()
    if used >= BUDGET:
        logger.warning("Jooble : quota atteint (%d/%d appels) — requête '%s' sautée",
                       used, BUDGET, params.get("keywords"))
        return []

    body = {
        "keywords": params.get("keywords", ""),
        "location": params.get("location", ""),
        "radius": str(params.get("radius", 40)),
        "page": "1",
        "ResultOnPage": str(RESULTS_PER_PAGE),
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            _count_call()
            resp = await client.post(SEARCH_URL.format(key=settings.jooble_api_key), json=body)
            resp.raise_for_status()
            jobs = (resp.json() or {}).get("jobs") or []
    except httpx.HTTPStatusError as e:
        logger.warning("Jooble '%s' : HTTP %s", params.get("keywords"), e.response.status_code)
        return []
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Jooble '%s' : %s", params.get("keywords"), e)
        return []

    out, seen = [], set()
    for r in jobs:
        o = normalize(r)
        if o and o["source_id"] not in seen:
            seen.add(o["source_id"])
            out.append(o)
    logger.info("Jooble '%s' → %d offres (%d/%d appels)", params.get("keywords"), len(out),
                used + 1, BUDGET)
    return out
