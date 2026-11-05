"""
Budget — application financière principale (Tailscale uniquement).

Opérations bancaires synchronisées (Enable Banking), catégories, fixes et reste à
vivre. Capital (investissements) reste un service distinct, résumé ici.
Patterns repris de job-radar : le conteneur sert son propre frontend, JWT
`sfauth` revérifié, SQLite WAL, boucles asyncio.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import jwt as _jwt
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import db
from config import settings
from routers import bank, misc, operations, overview, recurring
from services import scheduler, sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
# httpx journalise les URL complètes : le webhook Discord finirait dans les logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("budget")

if not settings.jwt_secret:
    raise RuntimeError("JWT_SECRET non défini dans l'environnement")

FRONTEND = Path(__file__).parent / "frontend"
PUBLIC_PATHS = {"/api/budget/health"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    sync.reparse_all()
    sync.dedupe_unreferenced()
    scheduler.start()
    logger.info("Budget ready.")
    yield
    scheduler.stop()


app = FastAPI(title="Budget", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422,
                        content={"detail": "Données invalides", "errors": exc.errors()[:5]})


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Défense en profondeur : JWT requis sur /api/* (cookie sfauth ou Bearer).
    Premier niveau : auth_request nginx."""
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC_PATHS or request.method == "OPTIONS":
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("sfauth")
    if token:
        try:
            _jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        except Exception:                                       # noqa: BLE001
            return JSONResponse(status_code=401, content={"detail": "Non authentifié"})
        # Hors du try : l'erreur d'une route reste une 500 journalisée, pas un faux 401.
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "Non authentifié"})


for r in (overview, operations, recurring, bank, misc):
    app.include_router(r.router)


@app.get("/api/budget/health")
async def health():
    return {"status": "ok", "service": "budget", "version": "1.0.0"}


@app.middleware("http")
async def frontend_revalidate(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


if FRONTEND.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(FRONTEND / "index.html")
else:
    logger.warning("Dossier frontend absent : %s", FRONTEND)
