"""
SQLite (WAL) — schéma v3 + migrations idempotentes.
Source de vérité : la table transactions. Les positions sont dérivées (services/valuation.py).
Trois comptes fixes (table accounts) ; les pointages (table checks) comparent le calcul au réel.
"""
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from config import settings

logger = logging.getLogger("capital.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    type TEXT NOT NULL,               -- buy | sell | dividend | fee
    isin TEXT,
    name TEXT,
    shares REAL DEFAULT 0,
    price REAL DEFAULT 0,
    amount REAL DEFAULT 0,            -- total EUR, toujours positif (le type porte le sens)
    fees REAL DEFAULT 0,
    account TEXT DEFAULT 'PEA',       -- accounts.id
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,              -- PEA | CRYPTO | PEE
    name TEXT NOT NULL,
    provider TEXT NOT NULL,           -- établissement qui fait foi
    cash REAL DEFAULT 0,              -- espèces non investies (relevées au pointage)
    sort INTEGER DEFAULT 0
);

-- Pointage : ce que l'établissement affiche, comparé au calcul à la même date.
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    date TEXT NOT NULL,
    source TEXT DEFAULT 'manuel',     -- manuel | pdf
    declared_total REAL,
    computed_total REAL,
    status TEXT NOT NULL,             -- ok | ecart
    lines TEXT,                       -- JSON : [{isin, name, declared_shares, computed_shares, ...}]
    adjustments INTEGER DEFAULT 0,    -- mouvements de rattrapage créés
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS asset_registry (
    isin TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ticker TEXT,
    asset_type TEXT DEFAULT 'stock',
    exchange TEXT,
    currency TEXT DEFAULT 'EUR',
    pea_eligible INTEGER DEFAULT 0,
    coingecko_id TEXT,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    sentiment TEXT,
    sentiment_score INTEGER,
    content TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prices_last (
    isin TEXT PRIMARY KEY,
    price REAL,
    currency TEXT DEFAULT 'EUR',
    price_eur REAL,
    change_24h REAL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS fx_rates (
    pair TEXT PRIMARY KEY,            -- ex: USDEUR
    rate REAL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    date TEXT PRIMARY KEY,            -- YYYY-MM-DD
    total_value REAL,
    total_invested REAL,
    pnl_eur REAL,
    pnl_pct REAL,
    by_account TEXT,                  -- JSON
    by_position TEXT,                 -- JSON
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT,
    kind TEXT NOT NULL,               -- price_above | price_below | pct_day | rsi_above | rsi_below
    threshold REAL NOT NULL,
    enabled INTEGER DEFAULT 1,
    cooldown_h INTEGER DEFAULT 24,
    last_fired TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER,
    isin TEXT,
    message TEXT,
    fired_at TEXT DEFAULT CURRENT_TIMESTAMP,
    read INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tx_isin ON transactions(isin);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_registry_ticker ON asset_registry(ticker);
"""

# Colonnes ajoutées sur tables existantes (ALTER échoue silencieusement si déjà présent)
ALTERS = [
    "ALTER TABLE transactions ADD COLUMN broker TEXT DEFAULT 'Trade Republic'",
    "ALTER TABLE transactions ADD COLUMN note TEXT",
    "ALTER TABLE asset_registry ADD COLUMN news_query TEXT",
    "ALTER TABLE asset_registry ADD COLUMN asset_class TEXT",
    "ALTER TABLE asset_registry ADD COLUMN target_weight REAL",
    # v3 — épargne salariale et traçabilité
    "ALTER TABLE transactions ADD COLUMN employer_amount REAL DEFAULT 0",   # abondement brut
    "ALTER TABLE transactions ADD COLUMN social_tax REAL DEFAULT 0",        # prélèvements sociaux
    "ALTER TABLE transactions ADD COLUMN available_on TEXT",                # date de disponibilité (PEE)
    "ALTER TABLE transactions ADD COLUMN source TEXT DEFAULT 'manuel'",     # manuel | pdf | pointage | reprise
    "ALTER TABLE transactions ADD COLUMN external_id TEXT",                 # dédoublonnage des imports
]

ACCOUNTS = [
    ("PEA", "PEA", "Trade Republic", 1),
    ("CRYPTO", "Bitcoin", "Trade Republic", 2),
    ("PEE", "PEE", "Natixis Interépargne", 3),
]
ACCOUNT_IDS = {a[0] for a in ACCOUNTS}


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
    r = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(conn, key: str, value: str):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def _guess_asset_class(name: str, asset_type: str) -> str:
    n = (name or "").lower()
    if asset_type == "crypto":
        return "crypto"
    if "monétaire" in n or "monetaire" in n or "money market" in n:
        return "monetary"
    if asset_type == "etf":
        return "etf"
    return "equity"


def _guess_news_query(name: str, asset_type: str) -> str:
    """Mots-clés courts pour les news — retire le jargon juridique/produit du nom légal."""
    if asset_type == "crypto":
        return name.split("(")[0].strip()
    stop = {"ucits", "etf", "sa", "s.a.", "se", "nv", "n.v.", "plc", "inc", "inc.", "swap",
            "acc", "dist", "i", "ii", "pea", "fund", "class", "shares", "ishares", "amundi",
            "lyxor", "bnp", "paribas", "easy", "vanguard", "spdr", "xtrackers"}
    words = [w for w in re.split(r"[\s\-–]+", name) if w and w.lower().strip(".,") not in stop]
    return " ".join(words[:3]) if words else name


def init():
    """Crée le schéma, applique les ALTER, migre les positions historiques en transactions."""
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        for stmt in ALTERS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass

        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_ext ON transactions(external_id) "
                     "WHERE external_id IS NOT NULL")
        conn.executemany("INSERT OR IGNORE INTO accounts (id, name, provider, sort) VALUES (?, ?, ?, ?)",
                         ACCOUNTS)

        _migrate_positions_to_transactions(conn)
        _migrate_v3(conn)
        _backfill_asset_metadata(conn)
        conn.commit()


def _migrate_v3(conn):
    """v3 (une fois) : comptes fixes. L'ancien « CTO » ne contenait que le Bitcoin Trade Republic ;
    le courtier découle désormais du compte (le PEE était rattaché à tort à Trade Republic)."""
    if get_meta(conn, "migrated_v3") == "1":
        return
    conn.execute("UPDATE transactions SET account = 'CRYPTO' WHERE account = 'CTO'")
    for acc_id, _, provider, _ in ACCOUNTS:
        conn.execute("UPDATE transactions SET broker = ? WHERE account = ?", (provider, acc_id))
    conn.execute("UPDATE transactions SET source = 'reprise', note = 'Reprise au 08/07/2026' "
                 "WHERE note = 'migration v2'")
    # Courtier libre et liste de suivi : remplacés par les comptes fixes, jamais utilisés.
    conn.execute("DROP TABLE IF EXISTS brokers")
    conn.execute("DROP TABLE IF EXISTS watchlist")
    set_meta(conn, "migrated_v3", "1")
    logger.info("Migration v3 : comptes PEA / CRYPTO / PEE")


def _migrate_positions_to_transactions(conn):
    """Migration v2 (une fois) : chaque position legacy → transaction d'ouverture 'buy'.

    La table positions est conservée en lecture seule (rollback possible) mais n'est
    plus jamais écrite. Vérifie l'égalité des montants investis avant/après.
    """
    if get_meta(conn, "migrated_v2") == "1":
        return
    has_positions = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='positions'"
    ).fetchone()
    if not has_positions:
        set_meta(conn, "migrated_v2", "1")
        return

    legacy = rows(conn.execute("SELECT * FROM positions WHERE shares > 0"))
    expected_invested = sum(p["shares"] * p["pru"] for p in legacy)
    migrated = 0
    for p in legacy:
        existing = conn.execute(
            "SELECT COUNT(*) c FROM transactions WHERE isin = ? AND note = 'migration v2'",
            (p["isin"],)
        ).fetchone()["c"]
        if existing:
            continue
        amount = round(p["shares"] * p["pru"], 2)
        date = (p["updated_at"] or datetime.now().isoformat())[:10]
        conn.execute("""
            INSERT INTO transactions (date, type, isin, name, shares, price, amount, fees,
                                      account, broker, note)
            VALUES (?, 'buy', ?, ?, ?, ?, ?, 0, ?, ?, 'migration v2')
        """, (date, p["isin"], p["name"], p["shares"], p["pru"], amount,
              p["account"], p["broker"] or "Trade Republic"))
        migrated += 1
        # Amorcer le cache de prix avec le dernier prix connu
        conn.execute("""
            INSERT OR IGNORE INTO prices_last (isin, price, currency, price_eur, change_24h, updated_at)
            VALUES (?, ?, 'EUR', ?, 0, ?)
        """, (p["isin"], p["current_price"], p["current_price"], p["updated_at"]))

    actual = conn.execute("""
        SELECT COALESCE(SUM(amount + fees), 0) s FROM transactions
        WHERE type = 'buy' AND note = 'migration v2'
    """).fetchone()["s"]
    if migrated and abs(actual - expected_invested) > 0.05:
        raise RuntimeError(
            f"Migration v2 incohérente : investi legacy {expected_invested:.2f}€ ≠ migré {actual:.2f}€"
        )
    set_meta(conn, "migrated_v2", "1")
    logger.info(f"Migration v2 : {migrated} position(s) → transactions d'ouverture "
                f"({actual:.2f}€ investis)")


def _backfill_asset_metadata(conn):
    """Renseigne asset_class et news_query pour les actifs qui n'en ont pas."""
    for a in rows(conn.execute("SELECT * FROM asset_registry")):
        updates, params = [], []
        if not a.get("asset_class"):
            updates.append("asset_class = ?")
            params.append(_guess_asset_class(a["name"], a["asset_type"]))
        if not a.get("news_query"):
            updates.append("news_query = ?")
            params.append(_guess_news_query(a["name"], a["asset_type"]))
        if updates:
            params.append(a["isin"])
            conn.execute(f"UPDATE asset_registry SET {', '.join(updates)} WHERE isin = ?", params)


# ── Accès simples partagés ────────────────────────────────────────────────────

def get_all_assets() -> list[dict]:
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM asset_registry ORDER BY name"))


def get_asset(isin: str) -> dict | None:
    with connect() as conn:
        r = conn.execute("SELECT * FROM asset_registry WHERE isin = ?", (isin,)).fetchone()
        return dict(r) if r else None


def get_transactions(account: str | None = None, limit: int = 100000) -> list[dict]:
    with connect() as conn:
        if account:
            cur = conn.execute(
                "SELECT * FROM transactions WHERE account = ? ORDER BY date DESC, id DESC LIMIT ?",
                (account, limit))
        else:
            cur = conn.execute("SELECT * FROM transactions ORDER BY date DESC, id DESC LIMIT ?", (limit,))
        return rows(cur)


def get_accounts() -> list[dict]:
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM accounts ORDER BY sort"))


def get_prices() -> dict[str, dict]:
    with connect() as conn:
        return {r["isin"]: dict(r) for r in conn.execute("SELECT * FROM prices_last").fetchall()}


def save_briefing(briefing: dict):
    date = briefing.get("date") or datetime.now().strftime("%d/%m/%Y")
    with connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO briefings (date, sentiment, sentiment_score, content)
            VALUES (?, ?, ?, ?)
        """, (date, briefing.get("market_sentiment"), briefing.get("sentiment_score"),
              json.dumps(briefing, ensure_ascii=False)))
        conn.commit()


def get_briefing(offset: int = 0) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM briefings ORDER BY id DESC LIMIT 1 OFFSET ?", (offset,)
        ).fetchone()
        total = conn.execute("SELECT COUNT(*) c FROM briefings").fetchone()["c"]
        if row:
            result = dict(row)
            result["content"] = json.loads(result["content"])
            result["total"] = total
            result["offset"] = offset
            return result
        return None
