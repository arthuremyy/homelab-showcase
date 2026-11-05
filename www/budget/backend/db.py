"""
SQLite (WAL) — schéma Budget + migrations idempotentes.

Source de vérité : la table `operations` (importées de la banque ou saisies).
Catégorie et rapprochement avec les fixes sont DÉRIVÉS (services/categorize.py,
services/recurring.py) — seule une catégorie choisie à la main (`category_locked`)
n'est jamais recalculée.
"""
import json
import logging
import sqlite3
from pathlib import Path

from config import settings

logger = logging.getLogger("budget.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS accounts (
    uid        TEXT PRIMARY KEY,          -- identifiant Enable Banking (ou 'manual')
    name       TEXT,
    iban_tail  TEXT,                      -- 4 derniers caractères seulement
    currency   TEXT DEFAULT 'EUR',
    balance    REAL,
    balance_at TEXT,
    synced_at  TEXT,
    active     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS categories (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL UNIQUE,
    kind     TEXT NOT NULL,               -- income | expense | savings | transfer
    position INTEGER DEFAULT 100,
    budget   REAL                         -- plafond mensuel facultatif (dépenses)
);

CREATE TABLE IF NOT EXISTS operations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ext_id          TEXT NOT NULL UNIQUE,
    account_uid     TEXT NOT NULL,
    date            TEXT NOT NULL,        -- YYYY-MM-DD (date d'opération)
    amount          REAL NOT NULL,        -- signé : + entrée, - sortie
    label           TEXT NOT NULL,
    counterparty    TEXT,
    status          TEXT DEFAULT 'BOOK',  -- BOOK | PDNG
    category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    category_locked INTEGER DEFAULT 0,
    source          TEXT DEFAULT 'bank',  -- bank | manual
    recurring_id    INTEGER,              -- fixe rattaché à la main (Ce mois › Rattacher)
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ops_date ON operations (date DESC);

CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT NOT NULL UNIQUE,     -- libellé normalisé (sous-chaîne)
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recurring (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL UNIQUE,     -- libellé normalisé + sens
    match_key   TEXT,                     -- contrepartie qui le règle (défaut : key). Plusieurs fixes
                                          -- peuvent partager la même : la CAF verse APL + prime en un virement
    label       TEXT NOT NULL,
    amount      REAL NOT NULL,            -- signé, montant mensuel attendu
    day         INTEGER,                  -- jour habituel du mois
    status      TEXT DEFAULT 'confirmed', -- confirmed | ignored
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

SEED_VERSION = "2"

# Catégories amorcées : (nom, nature, mots-clés sur le libellé normalisé).
# Les mots-clés sont des règles « système », toujours battues par les règles de l'utilisateur.
SEED = [
    ("Revenus",                 "income",   ["SALAIRE", "PAIE", "REMUNERATION"]),
    ("Aides",                   "income",   ["CAF", "ALLOCATION", "PRIME ACTIVITE", "FRANCE TRAVAIL", "CPAM",
                                             "AIDES APPRENTI", "AIDE"]),
    ("Logement",                "expense",  ["LOYER", "FONCIA", "NEXITY", "SYNDIC", "IMMO GESTION"]),
    ("Énergie",                 "expense",  ["EDF", "ENGIE", "TOTALENERGIES", "TOTAL ENERGIES", "VEOLIA",
                                             "EAU DE LA VILLE"]),
    ("Télécom et abonnements",  "expense",  ["FREE MOBILE", "FREE TELECOM", "ORANGE", "SFR", "BOUYGUES", "SOSH",
                                             "NETFLIX", "SPOTIFY", "DISNEY", "AMAZON PRIME", "APPLE COM", "GOOGLE",
                                             "ANTHROPIC", "OPENAI", "OVH", "CLOUDFLARE", "DEEZER", "CANAL"]),
    ("Assurances",              "expense",  ["SOGESSUR", "ASSURANCE", "MAAF", "MACIF", "MATMUT", "AXA", "ALLIANZ",
                                             "GMF", "MAIF", "LUKO"]),
    ("Crédits",                 "expense",  ["PRET", "SOGEFINANC", "SOGEFINANCEMENT", "ECHEANCE PRET", "COFIDIS", "CETELEM"]),
    ("Transport",               "expense",  ["SNCF", "TOTAL", "ESSO", "BP", "AVIA",
                                             "UBER", "BLABLACAR", "PEAGE", "APRR", "AREA", "AUTOROUTES", "PARKING",
                                             "RHONEXPRESS", "LIME", "DOTT", "CITIZ"]),
    ("Courses",                 "expense",  ["CARREFOUR", "LECLERC", "AUCHAN", "INTERMARCHE", "MONOPRIX", "FRANPRIX",
                                             "LIDL", "ALDI", "CASINO", "U EXPRESS", "SUPER U", "PICARD", "BIOCOOP",
                                             "GRAND FRAIS", "NATURALIA", "JERONIMO MARTINS", "SPAR", "PROXI",
                                             "LA VIE CLAIRE", "COCCINELLE", "VIVAL"]),
    ("Cantine et distributeurs", "expense", ["SODEXO", "CROUS", "IZLY", "REST UNIV", "RU", "SPL RU", "IVS",
                                             "MOKAMATIC", "ALFRAGEST", "SELECTA", "COMPASS", "ELIOR", "API RESTAURATION"]),
    ("Restaurants",             "expense",  ["RESTAURANT", "UBER EATS", "DELIVEROO", "MCDONALD", "BURGER KING",
                                             "BURGUER KING", "KFC", "BOULANGERIE", "FOURNIL", "BRASSERIE", "PIZZA",
                                             "SUSHI", "TANDOOR", "KEBAB", "STARBUCKS", "COLUMBUS"]),
    ("Tabac et presse",         "expense",  ["TABAC", "RELAY", "PRESSE"]),
    ("Santé",                   "expense",  ["PHARMACIE", "DOCTEUR", "MEDECIN", "MUTUELLE", "HOPITAL", "LABORATOIRE",
                                             "DENTISTE", "OPTICIEN"]),
    ("Loisirs",                 "expense",  ["FNAC", "CULTURA", "STEAM", "PLAYSTATION", "CINEMA", "PATHE", "UGC",
                                             "DECATHLON", "BASIC FIT", "FITNESS", "BDE", "BETCLIC", "WINAMAX",
                                             "FDJ", "PMU", "BAR"]),
    ("Voyages",                 "expense",  ["REVOLUT", "AIR FRANCE", "RYANAIR", "EASYJET", "VUELING", "TRANSAVIA",
                                             "BOOKING", "AIRBNB", "HOSTAL", "HOSTEL", "HOTEL", "FLIXBUS", "BLABLABUS"]),
    ("Achats",                  "expense",  ["AMAZON", "AMZN", "LEROY MERLIN", "IKEA", "ZARA", "H M", "VINTED",
                                             "ALIEXPRESS", "DARTY", "BOULANGER"]),
    ("Banque et frais",         "expense",  ["COTISATION", "FRAIS", "COMMISSION", "AGIOS", "INTERETS DEBITEURS"]),
    ("Impôts",                  "expense",  ["DGFIP", "IMPOT", "TRESOR PUBLIC"]),
    ("Épargne et investissement", "savings", ["TRADE REPUBLIC", "BOURSORAMA", "BOURSE DIRECT", "BINANCE", "COINBASE",
                                              "KRAKEN", "LIVRET", "PEA", "ASSURANCE VIE", "EPARGNE AUTOMATIQUE"]),
    ("Remboursements reçus",    "expense",  []),   # virements de particuliers : en déduction des dépenses
    ("Virements à des proches", "expense",  []),
    ("Virements internes",      "transfer", []),
    ("Retraits",                "expense",  ["RETRAIT DAB", "RETRAIT"]),
    ("Divers",                  "expense",  []),
]

DEFAULT_SETTINGS = {
    "low_balance": 100.0,          # alerte Discord sous ce solde (0 = désactivée)
    "caf_declaration_day": 1,      # rappel de déclaration trimestrielle (lot 2)
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(settings.db_path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def connect() -> sqlite3.Connection:
    return _conn()


def init() -> None:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(recurring)")}
        if "match_key" not in cols:
            c.execute("ALTER TABLE recurring ADD COLUMN match_key TEXT")
        if "recurring_id" not in {r[1] for r in c.execute("PRAGMA table_info(operations)")}:
            c.execute("ALTER TABLE operations ADD COLUMN recurring_id INTEGER")
        if "ident_hash" not in [r[1] for r in c.execute("PRAGMA table_info(accounts)")]:
            c.execute("ALTER TABLE accounts ADD COLUMN ident_hash TEXT")
        if get_meta("seed_version", c) != SEED_VERSION:
            # Ajoute les catégories manquantes et range les catégories système dans l'ordre du
            # SEED ; une catégorie créée ou renommée par l'utilisateur n'est jamais touchée.
            for i, (name, kind, _kw) in enumerate(SEED):
                c.execute("INSERT OR IGNORE INTO categories (name, kind, position) VALUES (?,?,?)",
                          (name, kind, i * 10))
                c.execute("UPDATE categories SET position = ? WHERE name = ?", (i * 10, name))
            set_meta("seed_version", SEED_VERSION, c)
            logger.info("Catégories amorcées (v%s, %d)", SEED_VERSION, len(SEED))


# ── meta ────────────────────────────────────────────────────────────────────

def get_meta(key: str, c: sqlite3.Connection | None = None) -> str | None:
    own = c is None
    c = c or _conn()
    try:
        r = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None
    finally:
        if own:
            c.close()


def set_meta(key: str, value: str | None, c: sqlite3.Connection | None = None) -> None:
    own = c is None
    c = c or _conn()
    try:
        if value is None:
            c.execute("DELETE FROM meta WHERE key = ?", (key,))
        else:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        if own:
            c.commit()
    finally:
        if own:
            c.close()


def get_json(key: str, default=None):
    raw = get_meta(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def set_json(key: str, value) -> None:
    set_meta(key, json.dumps(value, ensure_ascii=False))


def get_settings() -> dict:
    return {**DEFAULT_SETTINGS, **(get_json("settings", {}) or {})}


# ── lectures courantes ──────────────────────────────────────────────────────

def categories() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, name, kind, position, budget FROM categories ORDER BY position, name")]


def seed_keywords() -> dict[str, list[str]]:
    """Nom de catégorie → mots-clés système."""
    return {name: kw for name, _kind, kw in SEED}


def user_rules() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT r.id, r.pattern, r.category_id, c.name AS category "
            "FROM rules r JOIN categories c ON c.id = r.category_id ORDER BY r.pattern")]
