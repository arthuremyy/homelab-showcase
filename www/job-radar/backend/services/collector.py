"""
Collecte : interroge les sources, déduplique, écrit en base, score.

Idempotent par construction : une offre revue est mise à jour (last_seen_at,
seen_count) plutôt que dupliquée, grâce à UNIQUE(source, source_id) côté schéma
et au dedupe_hash pour le recoupement inter-sources.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import db
from services import dedupe, notify, scoring
from sources import adzuna, france_travail, jooble

logger = logging.getLogger("jobs.collector")

# Champs enrichis, remplis par les connecteurs quand la source les expose.
EXTRA_FIELDS = ("xp_label", "xp_required", "xp_level", "work_time", "company_size",
                "company_desc", "sector", "qualification", "travel", "skills",
                "n_positions", "few_candidates", "contract_detail", "updated_at")

CONNECTORS = {
    "france_travail": france_travail.fetch,
    "adzuna": adzuna.fetch,
    "jooble": jooble.fetch,
}

# Sources à cadence normale (toutes les JOBS_COLLECT_HOURS heures).
FREQUENT_SOURCES = ("france_travail",)
# Adzuna est au palier Trial (~1000 appels/mois) et n'expose aucun en-tête de
# quota : une seule passe par jour, sinon 4 passes × 5 requêtes = 600 appels/mois.
DAILY_SOURCES = ("adzuna", "jooble")

# Une offre est déclarée retirée après MISSING_LIMIT collectes consécutives sans
# la revoir ET au moins MISSING_HOURS sans nouvelle : des redémarrages rapprochés
# (une collecte à chaque démarrage) ne doivent pas suffire à la faire disparaître.
MISSING_LIMIT = 3
MISSING_HOURS = 24
# Filet global : une offre que rien n'a confirmée depuis STALE_HOURS (source en
# panne, bloquée ou débranchée) n'est plus présentée comme en ligne.
STALE_HOURS = 72
# Étapes dont l'état en ligne compte même si l'offre est déjà marquée retirée.
TRACKED = ("vivier", "candidate", "entretien", "offre")

# Sources en cours de collecte — lu par /overview pour afficher « collecte en cours ».
RUNNING: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extra(offer: dict, field: str):
    """Valeur d'un champ enrichi, sérialisée si c'est une liste (skills)."""
    v = offer.get(field)
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if field == "few_candidates":
        return int(bool(v))
    return v


def upsert_offer(conn, offer: dict) -> tuple[int, bool]:
    """Insère ou rafraîchit une offre. Retourne (offer_id, est_nouvelle)."""
    h = dedupe.compute_hash(offer)
    loose = dedupe.compute_loose_hash(offer)
    is_agg = int(dedupe.is_republished(offer))
    existing = conn.execute(
        "SELECT id FROM offers WHERE source=? AND source_id=?",
        (offer["source"], offer["source_id"])).fetchone()

    if existing:
        # Le salaire est re-dérivé à chaque passe : une correction du parseur doit
        # se propager sans recollecte complète.
        u_min, u_max = scoring.parse_salary(offer.get("salary_raw") or "")
        extra_sql = ", ".join(f"{f}=?" for f in EXTRA_FIELDS)
        conn.execute(
            "UPDATE offers SET last_seen_at=?, seen_count=seen_count+1, missing_runs=0, "
            "is_active=1, title=?, company=?, location=?, dept=?, remote=?, contract_type=?, "
            f"salary_raw=?, salary_min=?, salary_max=?, description=?, url=?, {extra_sql}, "
            "raw_json=? WHERE id=?",
            (_now(), offer["title"], offer.get("company"), offer.get("location"),
             offer.get("dept"), offer.get("remote"), offer.get("contract_type"),
             offer.get("salary_raw"), u_min, u_max,
             offer.get("description"), offer["url"],
             *(_extra(offer, f) for f in EXTRA_FIELDS),
             json.dumps(offer.get("_raw"), ensure_ascii=False)[:20000], existing["id"]))
        return existing["id"], False

    # Recoupement inter-sources : même poste déjà connu via une autre source.
    twin = conn.execute("SELECT id, source FROM offers WHERE dedupe_hash=?", (h,)).fetchone()
    if not twin:
        # Second filet : un agrégateur (Hellowork, Meteojob…) republie l'offre d'un
        # employeur sous son propre nom. La clé stricte ne peut pas les rapprocher,
        # donc on recoupe sur (titre, ville) dès qu'un des deux côtés est un agrégateur.
        twin = conn.execute(
            "SELECT id, source FROM offers WHERE loose_hash=? AND (is_aggregator=1 OR ?=1) LIMIT 1",
            (loose, is_agg)).fetchone()
    if twin:
        logger.debug("Doublon inter-sources ignoré (%s déjà vu via %s) : %s",
                     offer["source"], twin["source"], offer["title"][:60])
        conn.execute("UPDATE offers SET last_seen_at=?, missing_runs=0, is_active=1 WHERE id=?",
                     (_now(), twin["id"]))
        return twin["id"], False

    smin, smax = scoring.parse_salary(offer.get("salary_raw") or "")
    cols = ", ".join(EXTRA_FIELDS)
    marks = ",".join("?" * len(EXTRA_FIELDS))
    cur = conn.execute(
        "INSERT INTO offers (source, source_id, url, title, company, location, dept, remote, "
        "contract_type, salary_raw, salary_min, salary_max, description, posted_at, "
        f"first_seen_at, last_seen_at, dedupe_hash, loose_hash, is_aggregator, {cols}, raw_json) "
        f"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,{marks},?)",
        (offer["source"], offer["source_id"], offer["url"], offer["title"], offer.get("company"),
         offer.get("location"), offer.get("dept"), offer.get("remote"), offer.get("contract_type"),
         offer.get("salary_raw"), smin, smax, offer.get("description"), offer.get("posted_at"),
         _now(), _now(), h, loose, is_agg,
         *(_extra(offer, f) for f in EXTRA_FIELDS),
         json.dumps(offer.get("_raw"), ensure_ascii=False)[:20000]))
    oid = cur.lastrowid
    conn.execute("INSERT OR IGNORE INTO pipeline (offer_id, status) VALUES (?, 'nouveau')", (oid,))
    return oid, True


def score_one(conn, offer_id: int, profile: dict):
    r = conn.execute("SELECT * FROM offers WHERE id=?", (offer_id,)).fetchone()
    if not r:
        return
    o = dict(r)
    try:
        o["_raw"] = json.loads(o.get("raw_json") or "{}")
    except (ValueError, TypeError):
        o["_raw"] = {}
    s = scoring.score_offer(o, profile)
    conn.execute(
        "INSERT INTO scores (offer_id, track, match_score, match_breakdown, portability_score, "
        "portability_breakdown, lock_in_flag, below_floor, success_score, success_breakdown, "
        "engine_version, scored_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(offer_id) DO UPDATE SET "
        "track=excluded.track, match_score=excluded.match_score, match_breakdown=excluded.match_breakdown, "
        "portability_score=excluded.portability_score, portability_breakdown=excluded.portability_breakdown, "
        "lock_in_flag=excluded.lock_in_flag, below_floor=excluded.below_floor, "
        "success_score=excluded.success_score, "
        "success_breakdown=excluded.success_breakdown, engine_version=excluded.engine_version, "
        "scored_at=excluded.scored_at",
        (offer_id, s["track"], s["match_score"], json.dumps(s["match_breakdown"], ensure_ascii=False),
         s["portability_score"], json.dumps(s["portability_breakdown"], ensure_ascii=False),
         s["lock_in_flag"], s["below_floor"], s["success_score"],
         json.dumps(s["success_breakdown"], ensure_ascii=False),
         s["engine_version"], _now()))


def rescore_all() -> int:
    """Recalcule tous les scores, et re-dérive les salaires depuis leur libellé."""
    profile = db.get_profile()
    with db.connect() as conn:
        fixed = 0
        for r in conn.execute("SELECT id, salary_raw, salary_min FROM offers").fetchall():
            lo, hi = scoring.parse_salary(r["salary_raw"] or "")
            if lo != r["salary_min"]:
                conn.execute("UPDATE offers SET salary_min=?, salary_max=? WHERE id=?",
                             (lo, hi, r["id"]))
                fixed += 1
        if fixed:
            logger.info("Salaires re-dérivés : %d offres", fixed)
        ids = [r["id"] for r in conn.execute("SELECT id FROM offers")]
        for oid in ids:
            score_one(conn, oid, profile)
        conn.commit()
    logger.info("Rescore complet : %d offres", len(ids))
    return len(ids)


async def run_source(source: str) -> dict:
    """Exécute toutes les requêtes actives d'une source."""
    fetch = CONNECTORS.get(source)
    if not fetch:
        return {"source": source, "error": "connecteur inconnu"}

    with db.connect() as conn:
        queries = db.rows(conn.execute(
            "SELECT * FROM search_queries WHERE source=? AND enabled=1", (source,)))
        run = conn.execute("INSERT INTO runs (source) VALUES (?)", (source,))
        run_id = run.lastrowid
        conn.commit()

    fetched = created = errors = 0
    profile = db.get_profile()
    seen_ids: set[int] = set()
    new_ids: list[int] = []

    for q in queries:
        try:
            params = json.loads(q["params"])
            offers = await fetch(params)
        except Exception as e:                                  # noqa: BLE001 — une requête ratée ne doit pas tuer la passe
            logger.error("Requête '%s' échouée : %s", q["label"], e)
            errors += 1
            continue

        fetched += len(offers)
        with db.connect() as conn:
            for o in offers:
                try:
                    oid, is_new = upsert_offer(conn, o)
                    seen_ids.add(oid)
                    score_one(conn, oid, profile)
                    created += int(is_new)
                    if is_new:
                        new_ids.append(oid)
                except Exception as e:                          # noqa: BLE001
                    logger.error("Offre ignorée (%s) : %s", o.get("source_id"), e)
                    errors += 1
            conn.commit()

    if source == "france_travail" and fetched:
        await verify_france_travail(exclude=seen_ids)

    # Péremption : ce qui n'est plus remonté par la source finit désactivé.
    # Sauté quand la passe n'a RIEN rendu et n'a produit que des erreurs : une source
    # en panne (ou non configurée) ne doit pas désactiver l'historique qu'elle a bâti.
    with db.connect() as conn:
        if not seen_ids and fetched == 0:
            logger.info("Source %s : aucune offre rendue, péremption sautée", source)
        elif seen_ids:
            placeholders = ",".join("?" * len(seen_ids))
            conn.execute(
                f"UPDATE offers SET missing_runs = missing_runs + 1 "
                f"WHERE source=? AND is_active=1 AND id NOT IN ({placeholders})",
                (source, *seen_ids))
            conn.execute("UPDATE offers SET is_active=0 WHERE source=? AND missing_runs>=? "
                         "AND last_seen_at <= ?", (source, MISSING_LIMIT,
                         (datetime.now(timezone.utc) - timedelta(hours=MISSING_HOURS)).isoformat()))
        conn.execute("UPDATE runs SET ended_at=?, fetched=?, created=?, errors=? WHERE id=?",
                     (_now(), fetched, created, errors, run_id))
        conn.commit()

    logger.info("Collecte %s : %d récupérées, %d nouvelles, %d erreurs", source, fetched, created, errors)
    return {"source": source, "fetched": fetched, "created": created,
            "errors": errors, "new_ids": new_ids}


def _apply_checks(conn, etats: dict[str, bool], ids_by_sid: dict[str, int]) -> int:
    """Écrit le résultat d'une vérification. Rend le nombre d'offres retirées."""
    retirees = 0
    for sid, en_ligne in etats.items():
        oid = ids_by_sid[sid]
        if en_ligne:
            conn.execute("UPDATE offers SET is_active=1, missing_runs=0, last_seen_at=? WHERE id=?",
                         (_now(), oid))
        else:
            retirees += conn.execute("UPDATE offers SET is_active=0 WHERE id=? AND is_active=1",
                                     (oid,)).rowcount
    return retirees


async def verify_france_travail(exclude: set[int] = frozenset(), ids: list[int] | None = None) -> int:
    """Interroge France Travail offre par offre plutôt que d'attendre MISSING_LIMIT passes.

    Sans `ids` : toutes les offres FT actives non revues par la passe (`exclude`),
    plus celles du suivi, même déjà retirées (une annonce peut être republiée)."""
    with db.connect() as conn:
        if ids is not None:
            marks = ",".join("?" * len(ids)) or "NULL"
            rows = conn.execute(f"SELECT id, source_id FROM offers WHERE source='france_travail' "
                                f"AND id IN ({marks})", ids).fetchall()
        else:
            rows = conn.execute(
                "SELECT o.id, o.source_id FROM offers o LEFT JOIN pipeline p ON p.offer_id=o.id "
                "WHERE o.source='france_travail' AND (o.is_active=1 OR p.status IN (%s))"
                % ",".join("?" * len(TRACKED)), TRACKED).fetchall()
    cibles = {r["source_id"]: r["id"] for r in rows if r["id"] not in exclude}
    if not cibles:
        return 0
    etats = await france_travail.check(list(cibles))
    with db.connect() as conn:
        retirees = _apply_checks(conn, etats, cibles)
        conn.commit()
    if ids is None:
        logger.info("France Travail : %d offres vérifiées, %d retirées", len(etats), retirees)
    return retirees


def expire_stale() -> int:
    """Désactive ce que plus aucune source n'a confirmé depuis STALE_HOURS."""
    limite = (datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)).isoformat()
    with db.connect() as conn:
        n = conn.execute("UPDATE offers SET is_active=0 WHERE is_active=1 AND last_seen_at < ?",
                         (limite,)).rowcount
        conn.commit()
    if n:
        logger.info("Péremption : %d offres sans confirmation depuis %d h", n, STALE_HOURS)
    return n


async def alerter(new_ids: list[int]) -> int:
    """Pousse sur Discord les nouvelles offres au-dessus du seuil du profil.

    Seules les offres NOUVELLES sont candidates, et les postes marqués
    « enfermement » sont exclus : une alerte qui ramène vers l'OT irait contre
    l'objectif de l'outil.
    """
    if not new_ids:
        return 0
    profile = db.get_profile()
    try:
        seuil = int(profile.get("alert_min") or 85)
    except (TypeError, ValueError):
        seuil = 85

    marques = ",".join("?" * len(new_ids))
    with db.connect() as conn:
        lignes = db.rows(conn.execute(
            f"SELECT o.title, o.company, o.location, o.url, o.salary_raw, o.xp_label, "
            f"s.match_score, s.success_score FROM offers o JOIN scores s ON s.offer_id=o.id "
            f"WHERE o.id IN ({marques}) AND s.match_score >= ? "
            f"AND COALESCE(s.lock_in_flag, 0) = 0 "
            f"ORDER BY s.match_score DESC LIMIT 5", (*new_ids, seuil)))

    for r in lignes:
        details = " · ".join(x for x in (r["company"], r["location"], r["salary_raw"],
                                         r["xp_label"]) if x)
        await notify.send_embed(
            r["title"][:200], details, color="sienne", url=r["url"],
            fields=[{"name": "Matching", "value": f'{r["match_score"]}/100', "inline": True},
                    {"name": "Réussite", "value": f'{r["success_score"]}/100', "inline": True}])
    if lignes:
        logger.info("%d offre(s) notifiée(s) au-dessus de %d", len(lignes), seuil)
    return len(lignes)


async def run_sources(sources) -> list[dict]:
    resultats = []
    for s in sources:
        if s in RUNNING:                    # collecte manuelle pendant la passe planifiée
            continue
        RUNNING.add(s)
        try:
            resultats.append(await run_source(s))
        finally:
            RUNNING.discard(s)
    expire_stale()
    nouvelles = [i for r in resultats for i in r.get("new_ids", [])]
    try:
        await alerter(nouvelles)
    except Exception as e:                                  # noqa: BLE001
        logger.error("Alerte Discord : %s", e)              # ne doit jamais casser la collecte
    return resultats


async def run_all() -> list[dict]:
    """Toutes les sources — collecte manuelle depuis l'UI. Consomme du quota Adzuna."""
    return await run_sources(CONNECTORS)
