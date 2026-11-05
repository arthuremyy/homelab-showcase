"""Profil candidat et registre des requêtes de recherche."""
import json
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import db

logger = logging.getLogger("jobs.profile")
router = APIRouter(prefix="/api/jobs")


class ProfileUpdate(BaseModel):
    values: dict[str, str]


class QueryToggle(BaseModel):
    query_id: int
    enabled: bool


@router.get("/profile")
async def get_profile():
    with db.connect() as conn:
        profile = {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM profile")}
        queries = db.rows(conn.execute("SELECT * FROM search_queries ORDER BY id"))
    for q in queries:
        try:
            q["params"] = json.loads(q["params"])
        except (ValueError, TypeError):
            q["params"] = {}
    return {"status": "ok", "profile": profile, "queries": queries}


@router.post("/profile")
async def update_profile(u: ProfileUpdate):
    if not u.values:
        return JSONResponse(status_code=422, content={"error": "Aucune valeur fournie"})
    with db.connect() as conn:
        for k, v in u.values.items():
            conn.execute("INSERT INTO profile (key,value) VALUES (?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
        conn.commit()
    return {"status": "ok"}


@router.post("/query/toggle")
async def toggle_query(t: QueryToggle):
    with db.connect() as conn:
        conn.execute("UPDATE search_queries SET enabled=? WHERE id=?",
                     (int(t.enabled), t.query_id))
        conn.commit()
    return {"status": "ok"}
