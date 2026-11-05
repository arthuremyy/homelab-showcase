"""
HomeLab Capital Control v3 — API principale.
Source de vérité : transactions. Pointage des comptes contre l'établissement (Trade Republic, Natixis).
Scheduler intégré (prix, historique, briefing, alertes).
Le frontend est servi par nginx-dashboard — ce service n'expose que /api/*.
"""
import logging
from contextlib import asynccontextmanager

import jwt as _jwt
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import db
from config import settings
from services import scheduler
from routers import accounts, alerts, assets, briefing, portfolio, transactions

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
# httpx journalise les URL complètes : le webhook Discord finirait dans les logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("capital")

if not settings.jwt_secret:
    raise RuntimeError("JWT_SECRET non défini dans l'environnement")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Capital Control v3 starting...")
    db.init()
    scheduler.start()
    logger.info("Capital Control ready.")
    yield
    scheduler.stop()
    logger.info("Capital Control stopped.")


app = FastAPI(title="HomeLab Capital Control", version="3.0.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422,
                        content={"detail": "Données invalides", "errors": exc.errors()[:5]})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://capital.example.com"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Cookie"],
    allow_credentials=True,
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Défense en profondeur : JWT requis sur /api/* (cookie sfauth ou Bearer).
    Premier niveau : auth_request Nginx. Ce middleware protège l'accès direct au port 8100.
    """
    if not request.url.path.startswith("/api/") or request.method == "OPTIONS":
        return await call_next(request)

    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.cookies.get("sfauth")

    if token:
        try:
            _jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        except Exception:
            return JSONResponse(status_code=401, content={"detail": "Non authentifié"})
        # Hors du try : l'erreur d'une route reste une 500 journalisée, pas un faux 401.
        return await call_next(request)

    return JSONResponse(status_code=401, content={"detail": "Non authentifié"})


for r in (accounts, alerts, assets, briefing, portfolio, transactions):
    app.include_router(r.router)


@app.get("/")
async def index():
    """Healthcheck (utilisé par le HEALTHCHECK Docker)."""
    return {"status": "ok", "service": "capital-control", "version": "3.0.0"}
