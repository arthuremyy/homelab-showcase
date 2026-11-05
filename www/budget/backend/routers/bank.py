"""Connexion bancaire (Enable Banking) : consentement, synchronisation, état."""
import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import db
from clients import enablebanking as eb
from services import sync, views

logger = logging.getLogger("budget.bank")
router = APIRouter(prefix="/api/budget/bank")


def _psu(request: Request) -> dict:
    """En-têtes « utilisateur présent » : la lecture ne compte pas dans le quota DSP2."""
    h = {"Psu-User-Agent": request.headers.get("user-agent", "")[:200]}
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "")
    if ip:
        h["Psu-Ip-Address"] = ip
    return h


@router.get("/status")
async def status():
    return {**views.bank_status(), **views.balance()}


@router.post("/connect")
async def connect():
    if not eb.configured():
        raise HTTPException(409, "Enable Banking n'est pas configuré (EB_APP_ID et clé privée)")
    state = secrets.token_urlsafe(24)
    db.set_meta("eb_state", state)
    try:
        r = await eb.start_auth(state)
    except eb.EBError as e:
        raise HTTPException(502, e.detail)
    return {"url": r["url"]}


@router.get("/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None,
                   error: str | None = None):
    """Retour de la banque. Le code est à usage unique ; le state protège du rejeu."""
    expected = db.get_meta("eb_state")
    db.set_meta("eb_state", None)
    if error or not code or not expected or not secrets.compare_digest(state or "", expected):
        logger.warning("Retour bancaire refusé (error=%s)", error)
        return RedirectResponse("/?bank=error#/reglages", status_code=303)
    try:
        s = await eb.create_session(code)
    except eb.EBError as e:
        logger.error("Session : %s", e)
        return RedirectResponse("/?bank=error#/reglages", status_code=303)

    old = (db.get_json("eb_session") or {}).get("session_id")
    db.set_json("eb_session", {"session_id": s["session_id"],
                               "valid_until": (s.get("access") or {}).get("valid_until"),
                               "aspsp": (s.get("aspsp") or {}).get("name")})
    uids = []
    with db.connect() as c:
        for a in s.get("accounts", []):
            if not a.get("uid"):
                continue        # compte sans accès aux données (la banque le liste quand même)
            iban = ((a.get("account_id") or {}).get("iban") or "")
            name = a.get("name") or a.get("product") or "Compte"
            c.execute("INSERT INTO accounts (uid, name, iban_tail, currency, active) VALUES (?,?,?,?,1) "
                      "ON CONFLICT(uid) DO UPDATE SET name = excluded.name, iban_tail = excluded.iban_tail, "
                      "active = 1", (a["uid"], name, iban[-4:] or None,
                       a.get("currency") if a.get("currency") not in (None, "", "XXX") else "EUR"))
            uids.append(a["uid"])
            ident = a.get("identification_hash")
            if ident:
                c.execute("UPDATE accounts SET ident_hash = ? WHERE uid = ?", (ident, a["uid"]))
            # Même compte sous un nouvel uid : par empreinte stable, sinon par fin d'IBAN si unique.
            olds = c.execute("SELECT uid, ident_hash FROM accounts WHERE uid != ? AND uid != 'manual' "
                             "AND active = 1 AND ((? IS NOT NULL AND ident_hash = ?) OR "
                             "(ident_hash IS NULL AND ? != '' AND iban_tail = ?))",
                             (a["uid"], ident, ident, iban[-4:], iban[-4:])).fetchall()
            if len(olds) == 1:
                n = sync.rattacher_compte(c, olds[0]["uid"], a["uid"])
                logger.info("Consentement renouvelé : %d opération(s) rattachée(s)", n)
        # Un nouveau consentement redonne de nouveaux identifiants de compte : les opérations
        # restent, rattachées à l'ancien uid ; seul le compte est désactivé.
        if uids:
            q = ",".join("?" * len(uids))
            c.execute(f"UPDATE accounts SET active = 0 WHERE uid NOT IN ({q}) AND uid != 'manual'", uids)
    if old and old != s["session_id"]:
        try:
            await eb.delete_session(old)
        except eb.EBError:
            pass
    await sync.run(_psu(request))
    return RedirectResponse("/?bank=ok#/reglages", status_code=303)


@router.post("/sync")
async def sync_now(request: Request):
    r = await sync.run(_psu(request))
    if not r["ok"]:
        raise HTTPException(409 if "cours" in r["error"] else 502, r["error"])
    return r


@router.post("/disconnect")
async def disconnect():
    sess = db.get_json("eb_session") or {}
    if sess.get("session_id"):
        try:
            await eb.delete_session(sess["session_id"])
        except eb.EBError as e:
            logger.warning("Suppression de session : %s", e)
    db.set_meta("eb_session", None)
    return {"ok": True}
