"""Lectures composées partagées par les routers (aucune écriture)."""
from datetime import date, datetime, timedelta

import db
from services import recurring as rec


def kinds() -> dict[int, str]:
    with db.connect() as c:
        return {r["id"]: r["kind"] for r in c.execute("SELECT id, kind FROM categories")}


_OPS = ("SELECT o.id, o.date, o.amount, o.label, o.counterparty, o.status, o.category_id, "
        "o.category_locked, o.source, o.account_uid, o.recurring_id, c.name AS category, c.kind "
        "FROM operations o LEFT JOIN categories c ON c.id = o.category_id ")


def month_ops(month: str) -> list[dict]:
    with db.connect() as c:
        return [dict(r) for r in c.execute(_OPS + "WHERE substr(o.date, 1, 7) = ? ORDER BY o.date DESC, o.id DESC",
                                           (month,))]


def ops_since(day: str) -> list[dict]:
    with db.connect() as c:
        return [dict(r) for r in c.execute(_OPS + "WHERE o.date >= ? ORDER BY o.date DESC, o.id DESC", (day,))]


def confirmed() -> list[dict]:
    with db.connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, COALESCE(match_key, key) AS key, key AS own_key, label, amount, day "
            "FROM recurring WHERE status = 'confirmed' ORDER BY amount DESC")]


def with_presence(fixed: list[dict], today: date | None = None) -> list[dict]:
    """Ajoute `last_seen` et `missing` : un fixe absent de tout le mois précédent (alors qu'il
    était déjà attendu) est signalé — abonnement résilié, promotion terminée, salaire suspendu."""
    from services.categorize import key_of
    today = today or date.today()
    prev = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    last: dict[str, str] = {}
    with db.connect() as c:
        for r in c.execute("SELECT date, amount, COALESCE(counterparty, label) AS party FROM operations "
                           "WHERE status = 'BOOK' ORDER BY date"):
            last[key_of(r["party"], r["amount"])] = r["date"]
    out = []
    for r in fixed:
        seen = last.get(r["key"])
        out.append({**r, "last_seen": seen,
                    "missing": bool(seen and seen[:7] < prev),
                    "never_seen": seen is None})
    return out


def parties(days: int = 120) -> list[dict]:
    """Contreparties récentes (pour rattacher un fixe à l'opération qui le règle)."""
    from services.categorize import key_of
    since = (date.today() - timedelta(days=days)).isoformat()
    seen: dict[str, dict] = {}
    with db.connect() as c:
        for r in c.execute("SELECT date, amount, COALESCE(counterparty, label) AS party FROM operations "
                           "WHERE date >= ? AND status = 'BOOK' ORDER BY date DESC", (since,)):
            k = key_of(r["party"], r["amount"])
            e = seen.setdefault(k, {"key": k, "label": r["party"], "last_amount": r["amount"],
                                    "last_date": r["date"], "count": 0})
            e["count"] += 1
    return sorted(seen.values(), key=lambda e: (-e["count"], e["label"]))


def suggestions(today: date | None = None) -> list[dict]:
    today = today or date.today()
    since = (today - timedelta(days=rec.WINDOW_DAYS)).isoformat()
    with db.connect() as c:
        known = {k for r in c.execute("SELECT key, match_key FROM recurring") for k in (r[0], r[1]) if k}
        ops = [dict(r) for r in c.execute(
            "SELECT o.date, o.amount, COALESCE(o.counterparty, o.label) AS label "
            "FROM operations o LEFT JOIN categories c ON c.id = o.category_id "
            "WHERE o.status = 'BOOK' AND o.date >= ? AND COALESCE(c.kind, '') != 'transfer'", (since,))]
    return rec.detect(ops, today, known)


def last_category(counterparty: str) -> dict:
    """Catégorie de la dernière opération de cette contrepartie."""
    with db.connect() as c:
        r = c.execute("SELECT o.category_id, c.name AS category, c.kind FROM operations o "
                      "LEFT JOIN categories c ON c.id = o.category_id WHERE o.counterparty = ? "
                      "AND o.category_id IS NOT NULL ORDER BY o.date DESC LIMIT 1", (counterparty,)).fetchone()
    return dict(r) if r else {}


def vanished_pending() -> list[dict]:
    """Opérations en attente disparues, pas encore revenues comptabilisées (sync.still_vanished) :
    déjà déduites du solde, elles ne servent qu'à reconnaître les fixes réglés."""
    import json
    return [{**v, "id": -i, "status": "GONE", "category_locked": 1}
            for i, v in enumerate(json.loads(db.get_meta("vanished_pending") or "[]"), 1)]


def with_party(ops: list[dict]) -> list[dict]:
    """Libellé de rapprochement = contrepartie (comme la détection des fixes)."""
    return [{**o, "label": o.get("counterparty") or o["label"]} for o in ops]


def overdraft_ops(days: int = 365) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    with db.connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT date, amount, label FROM operations WHERE date >= ? AND "
            "(label LIKE 'INTERETS%' OR label LIKE 'COMMISSION D%INTERVENTION%' OR label LIKE 'RETROCESSION INTERET%')",
            (since,))]


def balance() -> dict:
    with db.connect() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT uid, name, iban_tail, balance, balance_at, synced_at FROM accounts "
            "WHERE active = 1 ORDER BY name")]
    known = [r["balance"] for r in rows if r["balance"] is not None]
    return {"accounts": rows, "total": round(sum(known), 2) if known else None}


def bank_status() -> dict:
    from clients import enablebanking as eb
    from services import sync
    sess = db.get_json("eb_session") or {}
    left = None
    if sess.get("valid_until"):
        try:
            vu = datetime.fromisoformat(sess["valid_until"].replace("Z", "+00:00"))
            left = (vu - datetime.now(vu.tzinfo)).days
        except ValueError:
            pass
    st = db.get_json("sync_state", {}) or {}
    return {
        "configured": eb.configured(),
        "connected": bool(sess.get("session_id")) and (left is None or left >= 0),
        "valid_until": sess.get("valid_until"),
        "days_left": left,
        "last_ok": st.get("last_ok"),
        "last_error": st.get("last_error"),
        "last_error_at": st.get("last_error_at"),
        "running": sync.running(),
    }


def months_available() -> list[str]:
    with db.connect() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT substr(date, 1, 7) FROM operations ORDER BY 1 DESC LIMIT 36")]


def trend(months: int = 6) -> list[dict]:
    """Entrées / sorties / épargne des N derniers mois (virements internes exclus)."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT substr(o.date, 1, 7) AS m, "
            "SUM(CASE WHEN COALESCE(c.kind, CASE WHEN o.amount > 0 THEN 'income' ELSE 'expense' END) = 'income' "
            "         THEN o.amount ELSE 0 END) AS income, "
            "SUM(CASE WHEN COALESCE(c.kind, CASE WHEN o.amount > 0 THEN 'income' ELSE 'expense' END) = 'expense' "
            "         THEN -o.amount ELSE 0 END) AS expenses, "
            "SUM(CASE WHEN c.kind = 'savings' THEN -o.amount ELSE 0 END) AS savings "
            "FROM operations o LEFT JOIN categories c ON c.id = o.category_id "
            "GROUP BY m ORDER BY m DESC LIMIT ?", (months,)).fetchall()
    return [{"month": r["m"], "income": round(r["income"] or 0, 2),
             "expenses": round(r["expenses"] or 0, 2), "savings": round(r["savings"] or 0, 2)}
            for r in reversed(rows)]


def category_avg(month: str, n: int = 3) -> dict:
    """Dépense moyenne par catégorie sur les `n` mois précédant `month`. Seuls les mois qui ont
    des opérations comptent, pour ne pas fausser la moyenne au début de l'historique."""
    y, m = map(int, month.split("-"))
    months = []
    for _ in range(n):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        months.append(f"{y}-{m:02d}")
    ph = ",".join("?" * n)
    with db.connect() as c:
        seen = c.execute(f"SELECT COUNT(DISTINCT substr(date, 1, 7)) FROM operations "
                         f"WHERE substr(date, 1, 7) IN ({ph})", months).fetchone()[0]
        if not seen:
            return {}
        rows = c.execute(
            "SELECT o.category_id AS id, SUM(-o.amount) AS spent "
            "FROM operations o LEFT JOIN categories c ON c.id = o.category_id "
            f"WHERE substr(o.date, 1, 7) IN ({ph}) "
            "AND COALESCE(c.kind, CASE WHEN o.amount > 0 THEN 'income' ELSE 'expense' END) = 'expense' "
            "GROUP BY o.category_id", months).fetchall()
    return {r["id"]: round(r["spent"] / seen, 2) for r in rows}


def livret() -> dict | None:
    """Livret A, sans accès bancaire direct : un solde connu à une date (Réglages) + les
    virements vers/depuis soi-même et l'épargne automatique (« Déclic seuil ») avant et après.
    Les intérêts annuels (versés au 31 décembre) n'apparaissent pas : recaler le solde en janvier."""
    from services import categorize as cz, sync
    anchor = db.get_settings().get("livret")
    if not anchor or anchor.get("amount") is None or not anchor.get("date"):
        return None
    with db.connect() as c:
        holder = sync.holder_words(c)
        rows = [dict(r) for r in c.execute(
            "SELECT o.date, o.amount, o.label FROM operations o JOIN categories c ON c.id = o.category_id "
            "WHERE c.kind = 'savings' AND o.status = 'BOOK' ORDER BY o.date")]
    flows = []                                  # (date, montant entré sur le livret)
    for r in rows:
        p = cz.parse_label(r["label"])
        if p["kind"] == "sweep" or cz.is_holder(cz.normalize(p["party"]), holder):
            flows.append((r["date"], -r["amount"]))
    a_date, a_amt = anchor["date"], float(anchor["amount"])

    def balance_at(day: str) -> float:          # solde en fin de journée `day`
        if day >= a_date:
            return a_amt + sum(f for d, f in flows if a_date < d <= day)
        return a_amt - sum(f for d, f in flows if day < d <= a_date)

    today = date.today()
    months, series = [], []
    y, m = today.year, today.month
    for _ in range(6):
        months.append(f"{y}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    for mo in reversed(months):
        yy, mm = map(int, mo.split("-"))
        end = (date(yy + (mm == 12), mm % 12 + 1, 1) - timedelta(days=1)).isoformat()
        series.append({"month": mo, "balance": round(balance_at(min(end, today.isoformat())), 2)})
    cur = today.strftime("%Y-%m")
    return {
        "balance": round(balance_at(today.isoformat()), 2),
        "anchor": {"amount": a_amt, "date": a_date},
        "month_flow": round(sum(f for d, f in flows if d.startswith(cur)), 2),
        "series": series,
    }
