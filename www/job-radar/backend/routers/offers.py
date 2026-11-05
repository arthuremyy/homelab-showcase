"""Endpoints des offres : liste filtrée, fiche détaillée, pipeline, collecte."""
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import db
from config import settings
from services import actions, collector, scoring

logger = logging.getLogger("jobs.offers")
router = APIRouter(prefix="/api/jobs")

# Étapes v2. « ecarte » vient du bouton Passer du tri : volume élevé, exclu du suivi.
STAGES_ACTIVES = ("vivier", "candidate", "entretien", "offre")
STAGES_CLOSES = ("refuse", "sans_reponse", "decline")
VALID_STATUS = {"nouveau", "ecarte", *STAGES_ACTIVES, *STAGES_CLOSES}

# Les seuils de relance vivent dans services/actions : le récapitulatif Discord
# et la vue « À faire » doivent reposer sur exactement les mêmes règles.
SORTS = {
    "match":       "s.match_score DESC",
    "portability": "s.portability_score DESC",
    "success":     "s.success_score DESC",
    "date":        "o.posted_at DESC",
    "salary":      "o.salary_max DESC",
}


class ListFilters(BaseModel):
    """Filtres en body JSON — jamais en query params : ils fuiteraient dans les logs nginx."""
    q: str | None = None
    tracks: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    contracts: list[str] = Field(default_factory=list)
    depts: list[str] = Field(default_factory=list)
    min_match: int = 0
    max_age_days: int | None = None
    hide_lock_in: bool = False
    include_inactive: bool = False
    sort: str = "match"
    limit: int = 100
    offset: int = 0


class StatusUpdate(BaseModel):
    offer_id: int
    status: str
    note: str | None = None


def _parse(row: dict) -> dict:
    if row.get("skills"):
        try:
            row["skills"] = json.loads(row["skills"])
        except (ValueError, TypeError):
            row["skills"] = []
    for f in ("match_breakdown", "portability_breakdown", "success_breakdown"):
        if row.get(f):
            try:
                row[f] = json.loads(row[f])
            except (ValueError, TypeError):
                row[f] = []
    row.pop("raw_json", None)
    if row.get("success_score") is not None:
        row["success_band"] = scoring.band(row["success_score"])
    return row


@router.post("/list")
async def list_offers(f: ListFilters):
    where, args = [], []
    if not f.include_inactive:
        where.append("o.is_active = 1")
    if f.q:
        where.append("(o.title LIKE ? OR o.company LIKE ? OR o.description LIKE ?)")
        args += [f"%{f.q}%"] * 3
    for field, values, col in (("tracks", f.tracks, "s.track"),
                               ("contracts", f.contracts, "o.contract_type"),
                               ("depts", f.depts, "o.dept"),
                               ("statuses", f.statuses, "p.status")):
        if values:
            where.append(f"{col} IN ({','.join('?' * len(values))})")
            args += values
    if f.min_match:
        where.append("s.match_score >= ?")
        args.append(f.min_match)
    if f.max_age_days:
        where.append("o.posted_at >= datetime('now', ?)")
        args.append(f"-{int(f.max_age_days)} days")
    if f.hide_lock_in:
        where.append("COALESCE(s.lock_in_flag,0) = 0")

    sql = (
        "SELECT o.*, s.track, s.match_score, s.portability_score, s.success_score, "
        "s.lock_in_flag, s.below_floor, COALESCE(p.status,'nouveau') AS status, "
        "p.updated_at AS moved_at, p.applied_at, p.last_followup_at "
        "FROM offers o LEFT JOIN scores s ON s.offer_id=o.id "
        "LEFT JOIN pipeline p ON p.offer_id=o.id "
        + ("WHERE " + " AND ".join(where) if where else "")
        + f" ORDER BY {SORTS.get(f.sort, SORTS['match'])} NULLS LAST LIMIT ? OFFSET ?")
    args += [min(f.limit, 500), f.offset]

    with db.connect() as conn:
        items = [_parse(r) for r in db.rows(conn.execute(sql, args))]
        total = conn.execute(
            "SELECT COUNT(*) c FROM offers o LEFT JOIN scores s ON s.offer_id=o.id "
            "LEFT JOIN pipeline p ON p.offer_id=o.id "
            + ("WHERE " + " AND ".join(where) if where else ""), args[:-2]).fetchone()["c"]
    return {"status": "ok", "total": total, "items": items}


# Une fiche France Travail ouverte est revérifiée en direct si sa dernière
# confirmation date de plus que ce délai : le lien affiché ne doit pas mener à une 404.
LIVE_CHECK_MIN = 15


@router.get("/offer/{offer_id}")
async def get_offer(offer_id: int):
    with db.connect() as conn:
        o = conn.execute("SELECT source, last_seen_at FROM offers WHERE id=?", (offer_id,)).fetchone()
    if o and o["source"] == "france_travail":
        limite = (datetime.now(timezone.utc) - timedelta(minutes=LIVE_CHECK_MIN)).isoformat()
        if (o["last_seen_at"] or "") < limite:
            await collector.verify_france_travail(ids=[offer_id])
    with db.connect() as conn:
        r = conn.execute(
            "SELECT o.*, s.track, s.match_score, s.match_breakdown, s.portability_score, "
            "s.portability_breakdown, s.lock_in_flag, s.below_floor, s.success_score, s.success_breakdown, "
            "COALESCE(p.status,'nouveau') AS status, p.note, p.applied_at, "
            "p.last_followup_at, p.updated_at AS moved_at "
            "FROM offers o LEFT JOIN scores s ON s.offer_id=o.id "
            "LEFT JOIN pipeline p ON p.offer_id=o.id WHERE o.id=?", (offer_id,)).fetchone()
    if not r:
        return JSONResponse(status_code=404, content={"error": "Offre introuvable"})
    return {"status": "ok", "offer": _parse(dict(r))}


@router.post("/status")
async def set_status(u: StatusUpdate):
    if u.status not in VALID_STATUS:
        return JSONResponse(status_code=422, content={"error": f"Statut invalide : {u.status}"})
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pipeline (offer_id, status, note, updated_at) VALUES (?,?,?,datetime('now')) "
            "ON CONFLICT(offer_id) DO UPDATE SET status=excluded.status, "
            "note=COALESCE(excluded.note, pipeline.note), updated_at=datetime('now')",
            (u.offer_id, u.status, u.note))
        # La date de candidature est posée SEULE, au premier passage en
        # « candidate » : c'est elle qui permet de calculer les relances sans
        # jamais rien demander à l'utilisateur.
        if u.status == "candidate":
            conn.execute("UPDATE pipeline SET applied_at=COALESCE(applied_at, datetime('now')) "
                         "WHERE offer_id=?", (u.offer_id,))
        conn.commit()
    return {"status": "ok"}


class OfferRef(BaseModel):
    offer_id: int


@router.post("/followup")
async def mark_followup(r: OfferRef):
    """Marque une relance comme faite : elle ressortira dans RELANCE_J jours."""
    with db.connect() as conn:
        conn.execute("UPDATE pipeline SET last_followup_at=datetime('now') WHERE offer_id=?",
                     (r.offer_id,))
        conn.commit()
    return {"status": "ok"}


@router.get("/todo")
async def todo():
    """Ce qui demande une action, toutes étapes confondues.

    Vue par défaut du suivi : elle répond à « qu'est-ce que je fais aujourd'hui »,
    question à laquelle une liste par étape ne répond pas.
    """
    return {"status": "ok",
            "groups": [{**g, "items": [_parse(dict(i)) for i in g["items"]]}
                       for g in actions.groups()]}


@router.get("/stages")
async def stages():
    """Effectifs par étape — alimente le sous-menu."""
    with db.connect() as conn:
        rows = db.rows(conn.execute(
            "SELECT p.status s, COUNT(*) c FROM pipeline p JOIN offers o ON o.id=p.offer_id "
            "GROUP BY p.status"))
        todo_n = 0
        for g in (await todo())["groups"]:
            todo_n += len(g["items"])
    return {"status": "ok", "counts": {r["s"]: r["c"] for r in rows}, "todo": todo_n}


@router.post("/deck")
async def deck(f: ListFilters):
    """File du mode deck : offres jamais tranchées, la meilleure d'abord.

    Renvoie la fiche COMPLÈTE (décompositions incluses) pour que le parcours
    carte par carte n'ait pas à refaire un aller-retour par offre.
    """
    where = ["o.is_active = 1", "COALESCE(p.status,'nouveau') = 'nouveau'"]
    args: list = []
    if f.min_match:
        where.append("s.match_score >= ?")
        args.append(f.min_match)
    if f.hide_lock_in:
        where.append("COALESCE(s.lock_in_flag,0) = 0")
    if f.tracks:
        where.append(f"s.track IN ({','.join('?' * len(f.tracks))})")
        args += f.tracks
    if f.max_age_days:
        where.append("o.posted_at >= datetime('now', ?)")
        args.append(f"-{int(f.max_age_days)} days")

    sql = ("SELECT o.*, s.track, s.match_score, s.match_breakdown, s.portability_score, "
           "s.portability_breakdown, s.lock_in_flag, s.below_floor, s.success_score, s.success_breakdown, "
           "COALESCE(p.status,'nouveau') AS status "
           "FROM offers o LEFT JOIN scores s ON s.offer_id=o.id "
           "LEFT JOIN pipeline p ON p.offer_id=o.id "
           "WHERE " + " AND ".join(where) +
           f" ORDER BY {SORTS.get(f.sort, SORTS['match'])} NULLS LAST LIMIT ?")

    with db.connect() as conn:
        items = [_parse(r) for r in db.rows(conn.execute(sql, args + [min(f.limit, 60)]))]
        remaining = conn.execute(
            "SELECT COUNT(*) c FROM offers o LEFT JOIN scores s ON s.offer_id=o.id "
            "LEFT JOIN pipeline p ON p.offer_id=o.id WHERE " + " AND ".join(where),
            args).fetchone()["c"]
    return {"status": "ok", "remaining": remaining, "items": items}


@router.post("/collect")
async def collect(bg: BackgroundTasks):
    """Collecte manuelle des sources sans quota (FREQUENT_SOURCES).

    Adzuna en est exclu : palier Trial, une passe par jour suffit à l'épuiser."""
    if collector.RUNNING:
        return {"status": "ok", "message": "Collecte déjà en cours"}
    bg.add_task(collector.run_sources, collector.FREQUENT_SOURCES)
    return {"status": "ok", "message": "Collecte lancée"}


# Une source est « en retard » si sa dernière passe réussie date de plus que
# son rythme normal + marge. Adzuna : quotidienne.
_CADENCE_H = {"france_travail": None, "adzuna": 24, "jooble": 24}
SOURCE_ENABLED = {
    "france_travail": lambda: bool(settings.ft_client_id and settings.ft_client_secret),
    "adzuna": lambda: bool(settings.adzuna_app_id and settings.adzuna_app_key),
    "jooble": lambda: bool(settings.jooble_api_key),
}


def _iso_utc(sqlite_ts: str | None) -> str | None:
    """CURRENT_TIMESTAMP SQLite (UTC, sans fuseau) → ISO avec fuseau, lisible par le navigateur."""
    if not sqlite_ts:
        return None
    if "T" in sqlite_ts:
        return sqlite_ts
    return sqlite_ts.replace(" ", "T") + "+00:00"


@router.get("/overview")
async def overview():
    """Tout ce que l'écran « Aujourd'hui » affiche, en un appel.

    Répond à trois questions : mes données sont-elles à jour, qu'ai-je à faire,
    qu'est-ce qui est arrivé de nouveau."""
    profile = db.get_profile()
    hide_ot = profile.get("hide_ot") != "0"
    lock = " AND COALESCE(s.lock_in_flag,0)=0" if hide_ot else ""
    now = datetime.now(timezone.utc)

    with db.connect() as conn:
        sources = []
        for src in ("france_travail", "adzuna", "jooble"):
            last = conn.execute(
                "SELECT * FROM runs WHERE source=? AND ended_at IS NOT NULL ORDER BY id DESC LIMIT 1",
                (src,)).fetchone()
            ok = conn.execute(
                "SELECT ended_at FROM runs WHERE source=? AND ended_at IS NOT NULL "
                "AND fetched > 0 ORDER BY id DESC LIMIT 1", (src,)).fetchone()
            actives = conn.execute(
                "SELECT COUNT(*) c FROM offers WHERE source=? AND is_active=1", (src,)).fetchone()["c"]
            cadence = _CADENCE_H[src] or max(1, settings.collect_hours)
            last_ok = ok["ended_at"] if ok else None
            late = True
            if last_ok:
                try:
                    late = now - datetime.fromisoformat(last_ok) > timedelta(hours=cadence * 1.5 + 1)
                except ValueError:
                    late = True
            sources.append({
                "source": src,
                "enabled": SOURCE_ENABLED[src](),
                "running": src in collector.RUNNING,
                "cadence_hours": cadence,
                "last_run_at": last["ended_at"] if last else None,
                "last_ok_at": last_ok,
                "fetched": last["fetched"] if last else 0,
                "created": last["created"] if last else 0,
                "errors": last["errors"] if last else 0,
                "active": actives,
                "late": late,
            })

        a_trier = conn.execute(
            "SELECT COUNT(*) c FROM offers o JOIN scores s ON s.offer_id=o.id "
            "LEFT JOIN pipeline p ON p.offer_id=o.id "
            "WHERE o.is_active=1 AND COALESCE(p.status,'nouveau')='nouveau' AND s.match_score >= 40"
            + lock).fetchone()["c"]
        pipeline = {r["s"]: r["c"] for r in conn.execute(
            "SELECT status s, COUNT(*) c FROM pipeline GROUP BY status")}
        nouveautes = db.rows(conn.execute(
            "SELECT o.id, o.title, o.company, o.location, o.contract_type, o.salary_min, o.salary_max, "
            "o.xp_label, o.xp_required, o.posted_at, o.first_seen_at, o.source, s.match_score "
            "FROM offers o JOIN scores s ON s.offer_id=o.id LEFT JOIN pipeline p ON p.offer_id=o.id "
            "WHERE o.is_active=1 AND COALESCE(p.status,'nouveau')='nouveau' AND s.match_score >= 55 "
            "AND o.first_seen_at >= ?" + lock + " ORDER BY s.match_score DESC LIMIT 8",
            ((now - timedelta(days=3)).isoformat(),)))
        nouvelles_24h = conn.execute(
            "SELECT COUNT(*) c FROM offers o JOIN scores s ON s.offer_id=o.id "
            "WHERE o.first_seen_at >= ? AND s.match_score >= 40" + lock,
            ((now - timedelta(days=1)).isoformat(),)).fetchone()["c"]

    groupes = [{**g, "items": [_parse(dict(i)) for i in g["items"]]} for g in actions.groups()]
    frequentes = [s for s in sources if s["source"] in collector.FREQUENT_SOURCES and s["last_run_at"]]
    derniere = max((s["last_run_at"] for s in frequentes), default=None)
    prochaine = None
    if derniere:
        try:
            prochaine = (datetime.fromisoformat(derniere)
                         + timedelta(hours=max(1, settings.collect_hours))).isoformat()
        except ValueError:
            prochaine = None
    return {
        "status": "ok",
        "now": now.isoformat(),
        "collecting": bool(collector.RUNNING),
        "last_collect_at": derniere,
        "next_collect_at": prochaine,
        "sources": sources,
        "counts": {
            "a_trier": a_trier,
            "nouvelles_24h": nouvelles_24h,
            "vivier": pipeline.get("vivier", 0),
            "candidate": pipeline.get("candidate", 0),
            "entretien": pipeline.get("entretien", 0),
            "offre": pipeline.get("offre", 0),
            "closes": sum(pipeline.get(k, 0) for k in STAGES_CLOSES),
            "ecarte": pipeline.get("ecarte", 0),
        },
        "todo": groupes,
        "nouveautes": nouveautes,
    }


@router.post("/rescore")
async def rescore(bg: BackgroundTasks):
    bg.add_task(collector.rescore_all)
    return {"status": "ok", "message": "Rescore lancé en arrière-plan"}


@router.get("/stats")
async def stats():
    with db.connect() as conn:
        by_track = db.rows(conn.execute(
            "SELECT COALESCE(s.track,'non_score') t, COUNT(*) c FROM offers o "
            "LEFT JOIN scores s ON s.offer_id=o.id WHERE o.is_active=1 GROUP BY t"))
        by_status = db.rows(conn.execute(
            "SELECT COALESCE(p.status,'nouveau') s, COUNT(*) c FROM offers o "
            "LEFT JOIN pipeline p ON p.offer_id=o.id WHERE o.is_active=1 GROUP BY s"))
        totals = dict(conn.execute(
            "SELECT COUNT(*) total, SUM(is_active) active FROM offers").fetchone())
        last_run = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return {"status": "ok", "totals": totals, "by_track": by_track,
            "by_status": by_status, "last_run": dict(last_run) if last_run else None}
