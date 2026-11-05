"""
Connecteur Adzuna — agrégateur multi-sources (API officielle).

Doc : https://developer.adzuna.com/
Authentification par `app_id` + `app_key` en paramètres de requête.

⚠ **Palier Trial : quota serré** (~1000 appels/mois). Adzuna n'expose aucun
en-tête de quota, donc la consommation n'est pas mesurable à l'exécution : le
connecteur est volontairement économe — **un seul appel par requête** (50
résultats, pas de pagination) et une seule passe par jour côté scheduler.
Soit ~5 appels/jour, ~150/mois. Ne pas ajouter de pagination sans revoir le palier.

Adzuna agrège d'autres sites : le champ `company` porte souvent le nom d'un job
board (Free-Work, Direct Emploi) plutôt que celui de l'employeur. La dédup par
clé lâche (titre + ville) s'en charge — voir services/dedupe.py.
"""
import logging
from datetime import datetime, timezone

import httpx

from config import settings
from sources.base import DEPT_BY_NAME, TIMEOUT, format_salary, infer_contract, strip_html

logger = logging.getLogger("jobs.adzuna")

BASE_URL = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
RESULTS_PER_PAGE = 50            # maximum autorisé en un appel


CONTRACT_MAP = {"permanent": "cdi", "contract": "cdd"}


def configured() -> bool:
    return bool(settings.adzuna_app_id and settings.adzuna_app_key)


def _iso(raw: str) -> str | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def normalize(r: dict) -> dict | None:
    oid = r.get("id")
    title = (r.get("title") or "").strip()
    if not oid or not title:
        return None

    loc = r.get("location") or {}
    area = loc.get("area") or []
    location = (loc.get("display_name") or "").strip()

    if area and area[0] and area[0].lower() != "france":
        dept = "INT"
    else:
        # area[2] = département. Hors AURA on laisse vide (neutre) plutôt que
        # d'inventer un code : les requêtes ciblent déjà Lyon et son rayon.
        dept = DEPT_BY_NAME.get(area[2].lower(), "") if len(area) > 2 else ""

    description = strip_html(r.get("description") or "")
    # Champ structuré prioritaire ; le texte ne sert que s'il est absent (70 % des cas).
    contract = CONTRACT_MAP.get((r.get("contract_type") or "").lower(), "unknown")
    if contract == "unknown":
        contract = infer_contract(f"{title} {description[:600]}")

    # `salary_is_predicted == "1"` signale une ESTIMATION statistique d'Adzuna,
    # pas un montant annoncé dans l'offre : on ne l'affiche pas comme un salaire réel.
    salary_raw = None
    if r.get("salary_is_predicted") == "0":
        # Adzuna ne normalise PAS la période : le montant est celui publié par la
        # source. format_salary déduit « mensuel » sous 10 000 €.
        salary_raw = format_salary(r.get("salary_min"), r.get("salary_max"))

    ctime = (r.get("contract_time") or "").lower()
    return {
        "source": "adzuna",
        "work_time": {"full_time": "Temps plein", "part_time": "Temps partiel"}.get(ctime),
        "sector": ((r.get("category") or {}).get("label") or "").strip() or None,
        "source_id": str(oid),
        "url": r.get("redirect_url") or "",
        "title": title,
        "company": ((r.get("company") or {}).get("display_name") or "").strip() or None,
        "location": location or None,
        "dept": dept,
        "remote": "unknown",
        "contract_type": contract,
        "salary_raw": salary_raw,
        "description": description or None,
        "posted_at": _iso(r.get("created")),
        "_raw": r,
    }


async def fetch(params: dict) -> list[dict]:
    """`params` : {'what': str, 'where': str, 'distance': int, 'max_days_old': int}."""
    if not configured():
        logger.debug("Adzuna non configuré (ADZUNA_APP_ID/KEY absents) — ignoré")
        return []

    query = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "results_per_page": RESULTS_PER_PAGE,
        "what": params.get("what", ""),
        "content-type": "application/json",
    }
    if params.get("where"):
        query["where"] = params["where"]
    if params.get("distance"):
        query["distance"] = params["distance"]
    if params.get("max_days_old"):
        query["max_days_old"] = params["max_days_old"]

    out: list[dict] = []
    seen: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(BASE_URL, params=query)
            resp.raise_for_status()
            results = (resp.json() or {}).get("results") or []
    except httpx.HTTPStatusError as e:
        # 429 = quota Trial épuisé. Ne pas réessayer dans la même passe.
        logger.warning("Adzuna '%s' : HTTP %s%s", params.get("what"), e.response.status_code,
                       " — quota Trial probablement épuisé" if e.response.status_code == 429 else "")
        return []
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Adzuna '%s' : %s", params.get("what"), e)
        return []

    for r in results:
        o = normalize(r)
        if o and o["url"] and o["source_id"] not in seen:
            seen.add(o["source_id"])
            out.append(o)

    logger.info("Adzuna '%s' → %d offres", params.get("what"), len(out))
    return out
