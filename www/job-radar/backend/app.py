"""
Job Radar — veille d'offres d'emploi cyber, accessible via Tailscale uniquement.

Ce service sert son PROPRE frontend : une seule image, un seul
vhost. Les patterns backend (lifespan, middleware JWT, SQLite WAL, scheduler
asyncio) reprennent capital-control.
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
from routers import offers, profile
from services import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("jobs")
# httpx journalise chaque URL en INFO, clés incluses (app_key Adzuna, webhook Discord).
logging.getLogger("httpx").setLevel(logging.WARNING)

if not settings.jwt_secret:
    raise RuntimeError("JWT_SECRET non défini dans l'environnement")

FRONTEND = Path(__file__).parent / "frontend"

# Sondes nginx : joignables sans JWT.
PUBLIC_PATHS = {"/api/jobs/health"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Job Radar starting...")
    db.init()
    scheduler.start()
    logger.info("Job Radar ready.")
    yield
    scheduler.stop()
    logger.info("Job Radar stopped.")


app = FastAPI(title="Job Radar", version="1.0.0", lifespan=lifespan,
              docs_url=None, redoc_url=None)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422,
                        content={"detail": "Données invalides", "errors": exc.errors()[:5]})


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Défense en profondeur : JWT requis sur /api/* (cookie sfauth ou Bearer).
    Premier niveau : auth_request nginx. Ce middleware protège l'accès direct au port 8400.
    Le nom du cookie est `sfauth` — identique au dashboard et à capital-control.
    """
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC_PATHS or request.method == "OPTIONS":
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else request.cookies.get("sfauth")

    if token:
        try:
            _jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
            return await call_next(request)
        except Exception:
            pass

    return JSONResponse(status_code=401, content={"detail": "Non authentifié"})


for r in (offers, profile):
    app.include_router(r.router)


@app.get("/api/jobs/health")
async def health():
    """Healthcheck sans auth (sonde nginx + HEALTHCHECK Docker)."""
    return {"status": "ok", "service": "job-radar", "version": "1.0.0"}


# Frontend : le navigateur revalide à chaque chargement (ETag, réponse 304 légère).
# Sans en-tête, il gardait l'ancienne interface plusieurs jours après un déploiement.
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
