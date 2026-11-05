"""
SQLite (WAL) — schéma Job Radar + migrations idempotentes.

Une offre = une ligne dans `offers`, dédupliquée inter-sources par `dedupe_hash`.
Les scores sont DÉRIVÉS (services/scoring.py) et stockés dans `scores` : ils sont
entièrement recalculables, jamais saisis à la main. Changer le moteur de scoring
revient à bumper ENGINE_VERSION et à relancer un rescore complet.
"""
import json
import logging
import sqlite3
from pathlib import Path

from config import settings

logger = logging.getLogger("jobs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS offers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,          -- france_travail | adzuna | jooble
    source_id     TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT,
    location      TEXT,
    dept          TEXT,                   -- code département ('69') ou 'INT' hors France
    remote        TEXT,                   -- none | partial | full | unknown
    contract_type TEXT,                   -- cdi | cdd | vie | alternance | stage | interim | unknown
    salary_raw    TEXT,
    salary_min    REAL,
    salary_max    REAL,
    description   TEXT,
    posted_at     TEXT,
    first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    seen_count    INTEGER DEFAULT 1,
    missing_runs  INTEGER DEFAULT 0,      -- collectes consécutives sans revoir l'offre
    is_active     INTEGER DEFAULT 1,
    -- Métadonnées enrichies. Toutes facultatives : chaque source n'en remplit
    -- qu'une partie (France Travail est de loin la plus généreuse).
    xp_label      TEXT,      -- « Débutant accepté », « 3 An(s) » — libellé de la source
    xp_required   INTEGER,   -- années exigées, dérivées du libellé (0 = débutant accepté)
    xp_level      TEXT,      -- debutant | souhaitee | exigee
    work_time     TEXT,      -- « 35H/semaine, travail en journée »
    company_size  TEXT,      -- « 20 à 49 salariés »
    company_desc  TEXT,
    sector        TEXT,
    qualification TEXT,      -- « Cadre »
    travel        TEXT,      -- « Ponctuels »
    skills        TEXT,      -- JSON [libellés]
    n_positions   INTEGER,
    few_candidates INTEGER DEFAULT 0,   -- la source signale un manque de candidats
    contract_detail TEXT,    -- « CDI », « CDD 6 mois »
    updated_at    TEXT,      -- dernière actualisation côté source
    dedupe_hash   TEXT NOT NULL,
    loose_hash    TEXT,
    is_aggregator INTEGER DEFAULT 0,
    raw_json      TEXT,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_offers_hash   ON offers (dedupe_hash);
CREATE INDEX IF NOT EXISTS idx_offers_active ON offers (is_active, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_offers_loose  ON offers (loose_hash);

CREATE TABLE IF NOT EXISTS scores (
    offer_id               INTEGER PRIMARY KEY REFERENCES offers(id) ON DELETE CASCADE,
    track                  TEXT,      -- cyber_indus | cyber_pur | ot_pur | hors_cible
    match_score            INTEGER,
    match_breakdown        TEXT,      -- JSON [{label, delta}]
    portability_score      INTEGER,
    portability_breakdown  TEXT,
    lock_in_flag           INTEGER DEFAULT 0,
    below_floor            INTEGER DEFAULT 0,
    success_score          INTEGER,
    success_breakdown      TEXT,
    engine_version         INTEGER,
    scored_at              TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_scores_match ON scores (match_score DESC);

CREATE TABLE IF NOT EXISTS enrichment (
    offer_id    INTEGER PRIMARY KEY REFERENCES offers(id) ON DELETE CASCADE,
    summary     TEXT,
    missions    TEXT,
    stack       TEXT,
    xp_required TEXT,
    certifs     TEXT,
    why_you     TEXT,
    gaps        TEXT,
    llm_adjust  INTEGER DEFAULT 0,
    model       TEXT,
    enriched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline (
    offer_id         INTEGER PRIMARY KEY REFERENCES offers(id) ON DELETE CASCADE,
    -- nouveau  : jamais tranchée (file du tri)
    -- ecarte   : passée pendant le tri — volume élevé, exclue du suivi
    -- vivier   : gardée, pas encore candidaté
    -- candidate | entretien | offre : en cours
    -- refuse | sans_reponse | decline : terminées, causes distinctes
    status           TEXT DEFAULT 'nouveau',
    note             TEXT,
    applied_at       TEXT,   -- posée AUTOMATIQUEMENT au passage en « candidate »
    last_followup_at TEXT,   -- dernière relance marquée comme faite
    updated_at       TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS companies (
    slug       TEXT PRIMARY KEY,
    name       TEXT,
    is_agency  INTEGER DEFAULT 0,
    seen_count INTEGER DEFAULT 0,
    notes      TEXT
);

CREATE TABLE IF NOT EXISTS search_queries (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    label   TEXT NOT NULL,
    source  TEXT NOT NULL,
    params  TEXT NOT NULL,          -- JSON passé au connecteur
    enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    ended_at   TEXT,
    fetched    INTEGER DEFAULT 0,
    created    INTEGER DEFAULT 0,
    errors     INTEGER DEFAULT 0,
    log        TEXT
);
"""

ALTERS: list[str] = [
    "ALTER TABLE offers ADD COLUMN loose_hash TEXT",
    "ALTER TABLE offers ADD COLUMN is_aggregator INTEGER DEFAULT 0",
    "ALTER TABLE offers ADD COLUMN xp_label TEXT",
    "ALTER TABLE offers ADD COLUMN xp_required INTEGER",
    "ALTER TABLE offers ADD COLUMN xp_level TEXT",
    "ALTER TABLE offers ADD COLUMN work_time TEXT",
    "ALTER TABLE offers ADD COLUMN company_size TEXT",
    "ALTER TABLE offers ADD COLUMN company_desc TEXT",
    "ALTER TABLE offers ADD COLUMN sector TEXT",
    "ALTER TABLE offers ADD COLUMN qualification TEXT",
    "ALTER TABLE offers ADD COLUMN travel TEXT",
    "ALTER TABLE offers ADD COLUMN skills TEXT",
    "ALTER TABLE offers ADD COLUMN n_positions INTEGER",
    "ALTER TABLE offers ADD COLUMN few_candidates INTEGER DEFAULT 0",
    "ALTER TABLE offers ADD COLUMN contract_detail TEXT",
    "ALTER TABLE offers ADD COLUMN updated_at TEXT",
    "ALTER TABLE scores ADD COLUMN below_floor INTEGER DEFAULT 0",
    "ALTER TABLE pipeline ADD COLUMN last_followup_at TEXT",
]

# Refonte des étapes (2026-09-09). Les anciennes ne représentaient ni le succès
# (« offre reçue ») ni le silence (« sans réponse »), et « à revoir » faisait
# doublon avec le vivier. Le « refuse » d'avant venait du bouton Passer du tri :
# c'est un écartement de ma part, pas un refus de l'entreprise — d'où « ecarte ».
STATUS_MIGRATION = {
    "shortlist": "vivier",
    "a_voir":    "vivier",
    "refuse":    "ecarte",
    "archive":   "ecarte",
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


def get_meta(conn, key: str) -> str | None:
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(conn, key: str, value: str):
    conn.execute("INSERT INTO meta (key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# ── Profil : valeurs de départ ────────────────────────────────────────────────
# Amorçage seulement. Éditable depuis l'UI, et le CV (lot 3) viendra l'affiner.
DEFAULT_PROFILE = {
    "diploma":        "Diplôme d'ingénieur en informatique, spécialité cybersécurité",
    "graduation":     "",
    "prior_diploma":  "",
    "experience":     "Profil d'exemple : à remplacer depuis l'interface.",
    "xp_years":       "3",
    "goal":           "Cybersécurité généraliste.",
    "geo":            "Paris / Île-de-France",
    "contracts":      "cdi",
    "salary_floor":   "",
    # Préférence d'affichage : masquer les postes OT / automatisme dans le tri.
    # « 1 » masque, « 0 » montre. Réglée dans Profil, plus dans la barre de tri.
    "hide_ot":        "1",
    # Notifications. Le webhook vit dans le PROFIL et non dans l'environnement :
    # modifiable sans redéploiement, et c'est déjà la forme multi-utilisateur.
    # Vide = repli sur DISCORD_WEBHOOK_JOBS (salon #news-job).
    "discord_webhook": "",
    "alert_min":       "85",    # alerte immédiate au-dessus de ce matching
    "digest_hour":     "08:00", # récapitulatif quotidien, heure locale
}

# Version du jeu de requêtes. L'incrémenter remplace le jeu en base au prochain
# démarrage (les désactivations manuelles des libellés conservés sont préservées).
QUERIES_SEED_VERSION = "8"

_AURA = ["01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"]

DEFAULT_QUERIES = [
    # France Travail — inactif tant que FT_CLIENT_ID/FT_CLIENT_SECRET sont absents.
    # Cette API rend la description INTÉGRALE de l'offre.
    ("Cybersécurité — AURA",  "france_travail", {"motsCles": "cybersécurité", "departements": _AURA}),
    ("Sécurité réseaux — AURA", "france_travail", {"motsCles": "sécurité informatique", "departements": _AURA}),
    ("SOC — AURA",           "france_travail", {"motsCles": "SOC", "departements": _AURA}),
    ("Pentest — AURA",       "france_travail", {"motsCles": "test intrusion", "departements": _AURA}),
    ("DevSecOps — AURA",     "france_travail", {"motsCles": "DevSecOps", "departements": _AURA}),

    # Adzuna — palier Trial : 1 appel par requête, 1 passe par jour (cf. sources/adzuna.py).
    # Garder ce jeu COURT : chaque requête ajoutée coûte ~30 appels/mois.
    ("Cybersécurité — Paris 40 km", "adzuna", {"what": "cybersécurité", "where": "Paris", "distance": 40, "max_days_old": 30}),
    ("Sécurité informatique — Paris", "adzuna", {"what": "sécurité informatique", "where": "Paris", "distance": 40, "max_days_old": 30}),
    ("SOC analyste — Paris",       "adzuna", {"what": "SOC analyste", "where": "Paris", "distance": 40, "max_days_old": 30}),
    ("Pentest — Paris",            "adzuna", {"what": "pentest", "where": "Paris", "distance": 50, "max_days_old": 30}),
    ("Cybersécurité — Grenoble",  "adzuna", {"what": "cybersécurité", "where": "Grenoble", "distance": 30, "max_days_old": 30}),

    # Jooble — 500 requêtes AU TOTAL : 3 requêtes/jour ≈ 5 mois. Ne pas allonger sans
    # avoir obtenu un quota plus large (cf. sources/jooble.py).
    ("Cybersécurité — Paris (Jooble)",     "jooble", {"keywords": "cybersécurité", "location": "Paris", "radius": 50}),
    ("Sécurité informatique — Paris (Jooble)", "jooble", {"keywords": "sécurité informatique", "location": "Paris", "radius": 50}),
    ("Cybersécurité — Grenoble (Jooble)", "jooble", {"keywords": "cybersécurité", "location": "Grenoble", "radius": 30}),
]


def init():
    """Crée le schéma, applique les ALTER, amorce profil et requêtes de recherche."""
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        for stmt in ALTERS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

        for k, v in DEFAULT_PROFILE.items():
            conn.execute("INSERT OR IGNORE INTO profile (key,value) VALUES (?,?)", (k, v))

        _seed_queries(conn)
        _migrate_statuses(conn)

        conn.commit()
    logger.info("Base prête : %s", settings.db_path)


def _migrate_statuses(conn):
    """Renomme les étapes historiques. Idempotent : marqué dans `meta`."""
    if get_meta(conn, "status_model") == "2":
        return
    for avant, apres in STATUS_MIGRATION.items():
        conn.execute("UPDATE pipeline SET status=? WHERE status=?", (apres, avant))
    set_meta(conn, "status_model", "2")
    logger.info("Étapes migrées vers le modèle v2")


def _seed_queries(conn):
    """Amorce ou met à jour le jeu de requêtes, en conservant les désactivations."""
    if get_meta(conn, "queries_seed_version") == QUERIES_SEED_VERSION:
        return
    disabled = {r["label"] for r in conn.execute(
        "SELECT label FROM search_queries WHERE enabled=0")}
    conn.execute("DELETE FROM search_queries")
    conn.executemany(
        "INSERT INTO search_queries (label, source, params, enabled) VALUES (?,?,?,?)",
        [(lbl, s, json.dumps(p, ensure_ascii=False), int(lbl not in disabled))
         for lbl, s, p in DEFAULT_QUERIES])
    set_meta(conn, "queries_seed_version", QUERIES_SEED_VERSION)
    logger.info("Jeu de requêtes v%s appliqué : %d requêtes", QUERIES_SEED_VERSION, len(DEFAULT_QUERIES))


def get_profile() -> dict:
    with connect() as conn:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM profile")}
