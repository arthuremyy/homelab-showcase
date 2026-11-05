"""
Synchronisation bancaire — Enable Banking → table `operations`.

Idempotente : les opérations comptabilisées sont insérées une seule fois (clé
`ext_id`) ; les opérations en attente sont remplacées à chaque passe, car leur
identifiant change quand la banque les comptabilise.
"""
import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import db
from clients import enablebanking as eb
from config import settings
from services import categorize

logger = logging.getLogger("budget.sync")

TZ = ZoneInfo(settings.tz)
FIRST_DAYS = 365          # profondeur de la première synchronisation (réduite si la banque refuse)
FALLBACK_DAYS = 89
OVERLAP_DAYS = 10         # relecture des derniers jours : opérations comptabilisées en retard
# Solde retenu : « disponible » d'abord (opérations en attente déjà déduites).
BALANCE_ORDER = ["ITAV", "XPCD", "CLAV", "OPAV", "ITBD", "CLBD", "OPBD"]

_lock = asyncio.Lock()


def running() -> bool:
    return _lock.locked()


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def parse(t: dict, uid: str) -> dict:
    """Transaction Enable Banking → opération (sans ext_id)."""
    amt = abs(float((t.get("transaction_amount") or {}).get("amount") or 0))
    credit = t.get("credit_debit_indicator") == "CRDT"
    party = (t.get("debtor") if credit else t.get("creditor")) or {}
    rem = t.get("remittance_information") or []
    label = " ".join(x for x in rem if x).strip() or party.get("name") or "Opération"
    # La banque ne transmet pas la contrepartie : elle est lue dans le libellé.
    name = party.get("name") or categorize.display(categorize.parse_label(label)["party"])
    return {
        "account_uid": uid,
        "date": (t.get("transaction_date") or t.get("booking_date") or t.get("value_date")
                 or date.today().isoformat())[:10],
        "amount": round(amt if credit else -amt, 2),
        "label": label[:300],
        "counterparty": (name or "")[:120] or None,
        "status": "PDNG" if t.get("status") == "PDNG" else "BOOK",
        "ref": t.get("entry_reference") or t.get("transaction_id"),
    } | ({"date": pending_date(label, date.today())} if (
        t.get("status") == "PDNG" and pending_date(label, date.today())) else {})


PENDING_DATE = re.compile(r"\bDU (\d{2})/(\d{2})(?:/(\d{2,4}))?\b")


def pending_date(label: str, today: date) -> str | None:
    """Date d'achat lue dans le libellé d'une opération en attente (« … DU 28/10 ») : la banque
    n'en donne pas d'autre, or la date de lecture décalerait l'achat de période."""
    m = PENDING_DATE.search(label or "")
    if not m:
        return None
    day, month = int(m[1]), int(m[2])
    for year in ([(2000 + int(m[3]) % 100)] if m[3] else [today.year, today.year - 1]):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d <= today:
            return d.isoformat()
    return None


def with_ids(ops: list[dict]) -> list[dict]:
    """Attribue `ext_id`. Sans référence bancaire, une empreinte du contenu + un rang
    pour distinguer deux achats identiques le même jour."""
    seen: dict[str, int] = {}
    for o in ops:
        if o["status"] == "BOOK" and o["ref"]:
            o["ext_id"] = f"eb:{o['account_uid']}:{o['ref']}"
            continue
        # En attente : sans la date, sinon l'identifiant change chaque jour et le rattachement se perd.
        base = (f"{o['account_uid']}|{o['amount']}|{o['label']}" if o["status"] == "PDNG"
                else f"{o['account_uid']}|{o['date']}|{o['amount']}|{o['label']}")
        n = seen[base] = seen.get(base, 0) + 1
        prefix = "p" if o["status"] == "PDNG" else "h"
        o["ext_id"] = f"{prefix}:" + hashlib.sha1(f"{base}|{n}".encode()).hexdigest()[:24]
    return ops


def rattacher_compte(c, old_uid: str, new_uid: str) -> int:
    """Nouveau consentement = nouvel uid pour le même compte : l'historique passe au nouvel uid et
    garde ses `ext_id`, sinon la relecture de 365 jours le dupliquerait. Renvoie le nombre déplacé."""
    rows = c.execute("SELECT id, ext_id, date, amount, label, status FROM operations "
                     "WHERE account_uid = ? AND source = 'bank' ORDER BY id", (old_uid,)).fetchall()
    seen: dict[str, int] = {}
    moved = 0
    for r in rows:
        ext = r["ext_id"] or ""
        if ext.startswith(f"eb:{old_uid}:"):
            new_ext = f"eb:{new_uid}:" + ext[len(f"eb:{old_uid}:"):]
        elif ext.startswith(("h:", "p:")):
            pending = r["status"] == "PDNG"
            base = (f"{new_uid}|{r['amount']}|{r['label']}" if pending
                    else f"{new_uid}|{r['date']}|{r['amount']}|{r['label']}")
            n = seen[base] = seen.get(base, 0) + 1
            new_ext = ("p:" if pending else "h:") + hashlib.sha1(f"{base}|{n}".encode()).hexdigest()[:24]
        else:
            new_ext = ext
        moved += c.execute("UPDATE OR IGNORE operations SET account_uid = ?, ext_id = ? WHERE id = ?",
                           (new_uid, new_ext, r["id"])).rowcount
    c.execute("UPDATE operations SET account_uid = ? WHERE account_uid = ? AND source != 'bank'",
              (new_uid, old_uid))
    if not c.execute("SELECT 1 FROM operations WHERE account_uid = ? LIMIT 1", (old_uid,)).fetchone():
        c.execute("DELETE FROM accounts WHERE uid = ?", (old_uid,))
    return moved


def pick_balance(bals: list[dict]) -> float | None:
    by_type = {b.get("balance_type"): b for b in bals}
    for t in BALANCE_ORDER:
        if t in by_type:
            return float(by_type[t]["balance_amount"]["amount"])
    return float(bals[0]["balance_amount"]["amount"]) if bals else None


def holder_words(c) -> set[str]:
    """Mots du nom du titulaire (« MARTIN Alex » → {MARTIN, ALEX}) : repère les virements vers soi-même."""
    words: set[str] = set()
    for r in c.execute("SELECT name FROM accounts WHERE uid IS NOT NULL AND uid != 'manual'"):
        words |= set(categorize.normalize(r["name"] or "").split())
    return words


def categorize_pending(c, only_null: bool = True) -> int:
    """(Re)catégorise les opérations non verrouillées. Renvoie le nombre modifié."""
    cats = {r["name"]: r["id"] for r in c.execute("SELECT id, name FROM categories")}
    holder = holder_words(c)
    rules = [dict(r) for r in c.execute("SELECT pattern, category_id FROM rules")]
    kw = db.seed_keywords()
    where = "category_locked = 0" + (" AND category_id IS NULL" if only_null else "")
    n = 0
    for o in c.execute(f"SELECT id, label, amount, category_id FROM operations WHERE {where}").fetchall():
        cid = categorize.match(o["label"], o["amount"], rules, kw, cats, holder)
        if cid != o["category_id"]:
            c.execute("UPDATE operations SET category_id = ? WHERE id = ?", (cid, o["id"]))
            n += 1
    return n


PARSE_VERSION = "3"


def reparse_all() -> None:
    """Après une évolution de la lecture des libellés : contrepartie relue et catégories
    recalculées (sauf celles posées à la main). Idempotent, marqué dans meta."""
    if db.get_meta("parse_version") == PARSE_VERSION:
        return
    with db.connect() as c:
        c.execute("DELETE FROM accounts WHERE uid IS NULL")
        rows = c.execute("SELECT id, label FROM operations WHERE source = 'bank'").fetchall()
        for r in rows:
            name = categorize.display(categorize.parse_label(r["label"])["party"])
            c.execute("UPDATE operations SET counterparty = ? WHERE id = ?", (name[:120] or None, r["id"]))
        n = categorize_pending(c, only_null=False)
        db.set_meta("parse_version", PARSE_VERSION, c)
    logger.info("Libellés relus (%d opérations, %d recatégorisées)", len(rows), n)


def same_party(a: str | None, b: str | None) -> bool:
    """Le libellé court tronque la contrepartie (« …Financement » / « …Financement E ») :
    égales, ou l'une commence l'autre au mot près."""
    a, b = (a or "").lower().split(), (b or "").lower().split()
    if len(a) > len(b):
        a, b = b, a
    return a == b or (bool(a) and b[:len(a)] == a)


def replace_unreferenced(c, new_id: int, keep: set[str]) -> None:
    """La banque envoie parfois une opération comptabilisée sans référence (libellé court), puis
    la même avec sa référence quelques jours plus tard : la première est retirée (catégorie
    posée à la main reprise). `keep` : ext_id de la passe en cours, jamais retirés."""
    n = c.execute("SELECT account_uid, date, amount, counterparty FROM operations WHERE id = ?",
                  (new_id,)).fetchone()
    old = next((r for r in c.execute(
        "SELECT id, ext_id, counterparty, category_id, category_locked, recurring_id FROM operations WHERE ext_id LIKE 'h:%' "
        "AND source = 'bank' AND account_uid = ? AND date = ? AND amount = ? ORDER BY id",
        (n["account_uid"], n["date"], n["amount"]))
        if r["ext_id"] not in keep and same_party(r["counterparty"], n["counterparty"])), None)
    if not old:
        return
    if old["category_locked"]:
        c.execute("UPDATE operations SET category_id = ?, category_locked = 1 WHERE id = ?",
                  (old["category_id"], new_id))
    if old["recurring_id"]:
        c.execute("UPDATE operations SET recurring_id = ? WHERE id = ?", (old["recurring_id"], new_id))
    c.execute("DELETE FROM operations WHERE id = ?", (old["id"],))


def announced(c, o: dict) -> bool:
    """La banque annonce un prélèvement quelques jours avant (libellé court, sans référence) puis
    l'envoie en attente le jour même : l'opération en attente ferait doublon."""
    return any(same_party(r["counterparty"], o["counterparty"]) for r in c.execute(
        "SELECT counterparty FROM operations WHERE ext_id LIKE 'h:%' AND source = 'bank' "
        "AND account_uid = ? AND date = ? AND amount = ?", (o["account_uid"], o["date"], o["amount"])))


def dedupe_unreferenced() -> int:
    """Rattrapage des doublons déjà en base (même règle que `replace_unreferenced`)."""
    with db.connect() as c:
        rows = c.execute("SELECT id FROM operations WHERE ext_id LIKE 'eb:%' AND source = 'bank' ORDER BY id").fetchall()
        before = c.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        for r in rows:
            replace_unreferenced(c, r["id"], set())
        n = before - c.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
    if n:
        logger.info("Doublons sans référence retirés : %d", n)
    return n


VANISHED_DAYS = 7


def still_vanished(vanished: list[dict], booked: list[dict], today: date) -> list[dict]:
    """Opérations en attente disparues de la banque avant d'y revenir comptabilisées (le loyer
    passe un jour ou deux dans ce trou, déjà déduit du solde). Gardées tant qu'aucune opération
    comptabilisée du même montant n'est apparue autour de leur date, 7 jours au plus.
    `booked` : [{date, amount}] comptabilisées récentes."""
    out = []
    for v in vanished:
        d = date.fromisoformat(v["date"])
        if (today - d).days > VANISHED_DAYS:
            continue
        lo, hi = (d - timedelta(days=3)).isoformat(), (d + timedelta(days=VANISHED_DAYS)).isoformat()
        if any(abs(b["amount"] - v["amount"]) < 0.005 and lo <= b["date"] <= hi for b in booked):
            continue
        out.append(v)
    return out


def store(uid: str, ops: list[dict]) -> int:
    """Écrit une passe : en attente remplacées, comptabilisées ajoutées. Renvoie les nouvelles."""
    with db.connect() as c:
        before = c.execute("SELECT COUNT(*) FROM operations WHERE status = 'BOOK'").fetchone()[0]
        links = {r["ext_id"]: r["recurring_id"] for r in c.execute(
            "SELECT ext_id, recurring_id FROM operations WHERE account_uid = ? AND status = 'PDNG' "
            "AND source = 'bank' AND recurring_id IS NOT NULL", (uid,))}
        gone = [dict(r) for r in c.execute(
            "SELECT ext_id, account_uid, date, amount, label, counterparty, recurring_id FROM operations "
            "WHERE account_uid = ? AND status = 'PDNG' AND source = 'bank'", (uid,))]
        c.execute("DELETE FROM operations WHERE account_uid = ? AND status = 'PDNG' AND source = 'bank'", (uid,))
        ops = with_ids(ops)
        ids = {o["ext_id"] for o in ops}
        for o in ops:
            if o["status"] == "PDNG" and announced(c, o):
                continue
            cur = c.execute("INSERT OR IGNORE INTO operations (ext_id, account_uid, date, amount, label, "
                            "counterparty, status) VALUES (?,?,?,?,?,?,?)",
                            (o["ext_id"], uid, o["date"], o["amount"], o["label"], o["counterparty"], o["status"]))
            if cur.rowcount and o["ext_id"] in links:
                c.execute("UPDATE operations SET recurring_id = ? WHERE id = ?", (links[o["ext_id"]], cur.lastrowid))
            if cur.rowcount and o["ext_id"].startswith("eb:"):
                replace_unreferenced(c, cur.lastrowid, ids)
        categorize_pending(c)
        old = json.loads(db.get_meta("vanished_pending", c) or "[]")
        cand = {v["ext_id"]: v for v in old + gone if v["ext_id"] not in ids}
        booked = [dict(r) for r in c.execute("SELECT date, amount FROM operations WHERE status = 'BOOK' AND date >= ?",
                                             ((date.today() - timedelta(days=VANISHED_DAYS + 3)).isoformat(),))]
        db.set_meta("vanished_pending", json.dumps(still_vanished(list(cand.values()), booked, date.today())), c)
        after = c.execute("SELECT COUNT(*) FROM operations WHERE status = 'BOOK'").fetchone()[0]
    return after - before


async def _sync_account(uid: str, psu: dict | None) -> int:
    with db.connect() as c:
        last = c.execute("SELECT MAX(date) FROM operations WHERE account_uid = ? AND status = 'BOOK'",
                         (uid,)).fetchone()[0]
    if last:
        since = (date.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)).isoformat()
        raw = await eb.transactions(uid, since, psu)
    else:
        try:
            raw = await eb.transactions(uid, (date.today() - timedelta(days=FIRST_DAYS)).isoformat(), psu)
        except eb.EBError as e:
            if e.status in (429, 401):
                raise
            logger.info("Historique long refusé (%s), repli sur %d jours", e.detail, FALLBACK_DAYS)
            raw = await eb.transactions(uid, (date.today() - timedelta(days=FALLBACK_DAYS)).isoformat(), psu)

    new = store(uid, [parse(t, uid) for t in raw])
    bal = pick_balance(await eb.balances(uid, psu))
    with db.connect() as c:
        c.execute("UPDATE accounts SET balance = ?, balance_at = ?, synced_at = ? WHERE uid = ?",
                  (bal, _now(), _now(), uid))
    return new


async def run(psu: dict | None = None) -> dict:
    """Une passe sur tous les comptes actifs. `psu` : en-têtes de l'utilisateur présent
    (synchronisation manuelle) — hors quota DSP2 des 4 lectures par jour."""
    if _lock.locked():
        return {"ok": False, "error": "Synchronisation déjà en cours"}
    async with _lock:
        state = db.get_json("sync_state", {}) or {}
        total = 0
        try:
            if not eb.configured():
                raise RuntimeError("Enable Banking non configuré")
            with db.connect() as c:
                uids = [r["uid"] for r in c.execute("SELECT uid FROM accounts WHERE active = 1 AND uid != 'manual'")]
            if not uids:
                return {"ok": False, "error": "Aucun compte relié"}
            for uid in uids:
                total += await _sync_account(uid, psu)
            state.update(last_ok=_now(), last_error=None, fails=0, last_new=total)
            db.set_json("sync_state", state)
            logger.info("Synchronisation : %d nouvelle(s) opération(s)", total)
            return {"ok": True, "new": total}
        except Exception as e:                                  # noqa: BLE001
            # Un délai dépassé (httpx) a un message vide : le type d'erreur est indispensable.
            msg = f"{type(e).__name__}: {e}".strip(": ")[:300]
            state.update(last_error=msg, last_error_at=_now(), fails=state.get("fails", 0) + 1)
            db.set_json("sync_state", state)
            logger.error("Synchronisation : %s", msg)
            return {"ok": False, "error": msg}
