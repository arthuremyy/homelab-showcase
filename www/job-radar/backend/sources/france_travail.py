"""
Connecteur France Travail — API « Offres d'emploi v2 ».

Doc : https://francetravail.io/data/api/offres-emploi
Authentification OAuth2 client_credentials, jeton valable ~25 min, mis en cache
et renouvelé automatiquement (marge de sécurité de 60 s).

L'API rend la **description intégrale** de l'offre, ce qui améliore nettement la
qualité du scoring.

Seule source vérifiable offre par offre : `GET /offres/{id}` rend 200 tant que
l'annonce est en ligne, 204 dès qu'elle est retirée (cf. `check`).
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx

from config import settings
from sources.base import (TIMEOUT, XP_LEVELS, dept_from_location, format_salary,
                          infer_contract, parse_xp_label, strip_html)

logger = logging.getLogger("jobs.france_travail")

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
DETAIL_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/{id}"
SCOPE = "api_offresdemploiv2 o2dsoffre"

PAGE_SIZE = 150          # l'API plafonne l'étendue de `range` à 149
MAX_PAGES = 4
PAGE_DELAY = 0.5
# L'API refuse (HTTP 400) au-delà de 5 départements par recherche :
# « Le nombre de départements maximum autorisé pour la recherche est de 5 ».
# Les 12 départements AURA sont donc interrogés en 3 lots successifs.
MAX_DEPTS_PER_QUERY = 5

# Codes contrat France Travail → vocabulaire interne.
CONTRACT_CODES = {
    "CDI": "cdi", "CDD": "cdd", "MIS": "interim", "SAI": "cdd",
    "CCE": "cdd", "FRA": "cdd", "LIB": "unknown", "REP": "unknown",
    "TTI": "interim", "DIN": "unknown",
}

_token: str | None = None
_token_exp: float = 0.0
_token_lock = asyncio.Lock()
# Cache d'échec : sans lui, un identifiant refusé provoque une tentative par requête
# (5 lignes d'erreur identiques par passe). On ne réessaie qu'après ce délai.
_auth_failed_until: float = 0.0
AUTH_FAIL_BACKOFF = 900


def configured() -> bool:
    return bool(settings.ft_client_id and settings.ft_client_secret)


async def _get_token(client: httpx.AsyncClient) -> str:
    """Jeton OAuth2 mis en cache. Renouvelé 60 s avant expiration."""
    global _token, _token_exp
    now = asyncio.get_event_loop().time()
    if _token and now < _token_exp:
        return _token

    async with _token_lock:
        now = asyncio.get_event_loop().time()
        if _token and now < _token_exp:            # double vérification sous verrou
            return _token
        resp = await client.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": settings.ft_client_id,
                "client_secret": settings.ft_client_secret,
                "scope": SCOPE,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        _token = payload["access_token"]
        _token_exp = now + max(60, int(payload.get("expires_in", 1500))) - 60
        logger.info("Jeton France Travail obtenu (valide %ss)", payload.get("expires_in"))
        return _token


def _iso(raw: str) -> str | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _clean_salary(raw: str | None) -> str | None:
    """« Annuel de 45000.0 Euros à 50000.0 Euros » → « 45 000 – 50 000 € brut annuel »."""
    if not raw:
        return None
    nums = re.findall(r"(\d+(?:\.\d+)?)", raw)
    vals = [int(float(n)) for n in nums if 10_000 <= float(n) <= 300_000]
    if not vals:
        return raw.strip() or None
    fmt = lambda v: f"{v:,}".replace(",", "\u202f")
    if len(vals) >= 2 and vals[0] != vals[-1]:
        return f"{fmt(vals[0])} – {fmt(vals[-1])} € brut annuel"
    return f"{fmt(vals[0])} € brut annuel"


def normalize(r: dict) -> dict | None:
    oid = r.get("id")
    title = (r.get("intitule") or "").strip()
    if not oid or not title:
        return None

    lieu = r.get("lieuTravail") or {}
    location = (lieu.get("libelle") or "").strip()
    # 'libelle' vaut souvent « 69 - LYON 03 » : le département est en tête.
    dept = ""
    if location[:2].isdigit():
        dept = location[:2]
    if not dept:
        cp = (lieu.get("codePostal") or "").strip()
        dept = cp[:2] if len(cp) >= 2 else dept_from_location(location)

    description = strip_html(r.get("description") or "")
    # L'API expose un code de contrat ET un booléen alternance : tous deux fiables.
    # Le texte n'intervient que s'ils sont muets.
    code = (r.get("typeContrat") or "").upper()
    contract = CONTRACT_CODES.get(code, "unknown")
    if r.get("alternance"):
        contract = "alternance"
    elif contract == "unknown":
        contract = infer_contract(f"{title} {description[:600]}")

    salaire = _clean_salary((r.get("salaire") or {}).get("libelle"))
    origine = r.get("origineOffre") or {}
    url = origine.get("urlOrigine") or f"https://candidat.francetravail.fr/offres/recherche/detail/{oid}"

    ent = r.get("entreprise") or {}
    skills = [c.get("libelle") for c in (r.get("competences") or []) if c.get("libelle")]
    work_time = " · ".join(x.strip() for x in (r.get("dureeTravailLibelle") or "").split("\n") if x.strip())
    xp_label = (r.get("experienceLibelle") or "").strip() or None

    return {
        "source": "france_travail",
        "xp_label": xp_label,
        "xp_required": parse_xp_label(xp_label),
        "xp_level": XP_LEVELS.get((r.get("experienceExige") or "").upper()),
        "work_time": work_time or None,
        "company_size": (r.get("trancheEffectifEtab") or "").strip() or None,
        "company_desc": (ent.get("description") or "").strip()[:600] or None,
        "sector": (r.get("secteurActiviteLibelle") or "").strip() or None,
        "qualification": (r.get("qualificationLibelle") or "").strip() or None,
        "travel": (r.get("deplacementLibelle") or "").strip() or None,
        "skills": skills[:12] or None,
        "n_positions": r.get("nombrePostes"),
        "few_candidates": bool(r.get("offresManqueCandidats")),
        "contract_detail": (r.get("typeContratLibelle") or "").strip() or None,
        "updated_at": _iso(r.get("dateActualisation")),
        "source_id": str(oid),
        "url": url,
        "title": title,
        "company": ((r.get("entreprise") or {}).get("nom") or "").strip() or None,
        "location": location or None,
        "dept": dept,
        "remote": "unknown",
        "contract_type": contract,
        "salary_raw": (salaire or "").strip() or None,
        "description": description or None,
        "posted_at": _iso(r.get("dateCreation")),
        "_raw": r,
    }


async def fetch(params: dict) -> list[dict]:
    """`params` : {'motsCles': str, 'departements': [codes], 'typeContrat': 'CDI'}."""
    if not configured():
        logger.debug("France Travail non configuré (FT_CLIENT_ID/SECRET absents) — ignoré")
        return []

    out: list[dict] = []
    seen: set[str] = set()

    global _auth_failed_until
    loop_now = asyncio.get_event_loop().time()
    if loop_now < _auth_failed_until:
        return []

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        try:
            token = await _get_token(client)
        except httpx.HTTPStatusError as e:
            _auth_failed_until = loop_now + AUTH_FAIL_BACKOFF
            logger.error("France Travail : jeton refusé (HTTP %s) %s — nouvel essai dans %d min. "
                         "Vérifier que l'API « Offres d'emploi v2 » est bien souscrite à "
                         "l'application sur francetravail.io et que le secret est à jour.",
                         e.response.status_code, e.response.text[:120], AUTH_FAIL_BACKOFF // 60)
            return []
        except (httpx.HTTPError, KeyError, ValueError) as e:
            _auth_failed_until = loop_now + AUTH_FAIL_BACKOFF
            logger.error("France Travail : obtention du jeton impossible : %s", e)
            return []

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        depts = [str(d) for d in (params.get("departements") or [])]
        # Un lot vide = recherche nationale (aucun filtre de département).
        batches = ([depts[i:i + MAX_DEPTS_PER_QUERY] for i in range(0, len(depts), MAX_DEPTS_PER_QUERY)]
                   or [[]])

        for batch in batches:
            for page in range(MAX_PAGES):
                start = page * PAGE_SIZE
                query = {
                    "motsCles": params.get("motsCles", ""),
                    "range": f"{start}-{start + PAGE_SIZE - 1}",
                }
                if batch:
                    query["departement"] = ",".join(batch)
                if params.get("typeContrat"):
                    query["typeContrat"] = params["typeContrat"]

                try:
                    resp = await client.get(SEARCH_URL, headers=headers, params=query)
                    # 204 = aucun résultat ; 206 = page partielle, donc dernière.
                    if resp.status_code == 204:
                        break
                    resp.raise_for_status()
                    results = (resp.json() or {}).get("resultats") or []
                except httpx.HTTPStatusError as e:
                    logger.warning("France Travail '%s' [%s] page %d : HTTP %s %s",
                                   params.get("motsCles"), ",".join(batch) or "national",
                                   page, e.response.status_code, e.response.text[:120])
                    break
                except (httpx.HTTPError, ValueError) as e:
                    logger.warning("France Travail '%s' page %d : %s", params.get("motsCles"), page, e)
                    break

                for r in results:
                    o = normalize(r)
                    if o and o["source_id"] not in seen:
                        seen.add(o["source_id"])
                        out.append(o)

                if len(results) < PAGE_SIZE or resp.status_code == 206:
                    break
                await asyncio.sleep(PAGE_DELAY)

    logger.info("France Travail '%s' → %d offres", params.get("motsCles"), len(out))
    return out


async def check(ids: list[str]) -> dict[str, bool]:
    """État en ligne de chaque offre : True = publiée, False = retirée (204/404).

    Une erreur (réseau, 5xx, jeton) n'apparaît pas dans le résultat : on ne
    déclare jamais une offre retirée sur une réponse ambiguë."""
    if not ids or not configured():
        return {}
    out: dict[str, bool] = {}
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        try:
            token = await _get_token(client)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            logger.warning("France Travail : vérification impossible (jeton) : %s", e)
            return {}
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        for oid in ids:
            try:
                resp = await client.get(DETAIL_URL.format(id=oid), headers=headers)
            except httpx.HTTPError as e:
                logger.warning("France Travail : vérification %s : %s", oid, e)
                continue
            if resp.status_code == 200:
                out[oid] = True
            elif resp.status_code in (204, 404):
                out[oid] = False
            else:
                logger.warning("France Travail : vérification %s : HTTP %s", oid, resp.status_code)
            await asyncio.sleep(0.15)          # l'API tolère ~10 appels/s
    return out
