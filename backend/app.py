import ipaddress
import json
import os
import threading
import urllib.request
from fastapi import FastAPI, Request, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from collections import defaultdict
import asyncio
import logging
import time

from metrics import MetricsCollector
from database import MetricsDB
from auth import verify_password, create_token, verify_token
from speedtest_runner import SpeedTestRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("api")

# Limites de connexion en mémoire : par client (5 essais / 60 s) et, en plus, plafond global d'échecs
_login_attempts: dict[str, list[float]] = defaultdict(list)
_login_failures: list[float] = []
_RATE_LIMIT = 5
_RATE_WINDOW = 60
_GLOBAL_FAILURES = 20
_ALERT_EVERY = 1800
_last_alert = 0.0
_bcrypt_slots = asyncio.Semaphore(2)


def _rate_key(ip: str) -> str:
    """Clé de limite : une IPv6 compte par /64, le bloc que détient un même client."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6 and not addr.ipv4_mapped:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return ip


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    # Retire les clés périmées : sinon la mémoire croît avec chaque adresse vue
    for k in [k for k, v in _login_attempts.items() if not v or now - v[-1] >= _RATE_WINDOW]:
        del _login_attempts[k]
    key = _rate_key(ip)
    _login_attempts[key] = [t for t in _login_attempts[key] if now - t < _RATE_WINDOW]
    if len(_login_attempts[key]) >= _RATE_LIMIT:
        return False
    _login_attempts[key].append(now)
    return True


def _global_limit_reached() -> bool:
    now = time.time()
    _login_failures[:] = [t for t in _login_failures if now - t < _RATE_WINDOW]
    return len(_login_failures) >= _GLOBAL_FAILURES


def _alert_discord() -> None:
    """Alerte `#news-health`, 1 fois par 30 min au plus. Ne bloque jamais la connexion."""
    global _last_alert
    url = os.getenv("DISCORD_WEBHOOK_HEALTH")
    if not url or time.time() - _last_alert < _ALERT_EVERY:
        return
    _last_alert = time.time()
    body = json.dumps({"content": "⚠️ Connexion HomeLab : plafond d'échecs atteint, attaque possible."}).encode()

    def send():
        try:
            req = urllib.request.Request(url, data=body, method="POST", headers={
                "Content-Type": "application/json", "User-Agent": "HomeLab"})
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as e:                                  # noqa: BLE001
            logger.warning("Alerte Discord : %s", type(e).__name__)

    threading.Thread(target=send, daemon=True).start()


def _client_ip(request: Request) -> str:
    """Vraie IP client. Cloudflare écrase `CF-Connecting-IP` ; côté Tailscale et LAN, nginx-proxy-local aussi."""
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

collector = MetricsCollector()
db = MetricsDB()
speedtest = SpeedTestRunner(docker_client=collector._docker)


async def periodic_save():
    """Sauvegarder les métriques en BDD toutes les 30s."""
    while True:
        await asyncio.sleep(30)
        try:
            data = collector.get_current()
            if data and "timestamp" in data:
                db.save(data)
        except Exception as e:
            logger.error(f"Periodic save error: {e}")


async def periodic_cleanup():
    """Nettoyage des anciennes données toutes les 24h."""
    while True:
        await asyncio.sleep(86400)
        try:
            db.cleanup(days=30)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Monitoring API...")
    db.init()
    collector.start()
    save_task = asyncio.create_task(periodic_save())
    cleanup_task = asyncio.create_task(periodic_cleanup())
    # Save initial snapshot after 10s
    async def initial_save():
        await asyncio.sleep(10)
        try:
            db.save(collector.get_current())
        except Exception:
            pass
    asyncio.create_task(initial_save())
    logger.info("API ready")
    yield
    collector.stop()
    save_task.cancel()
    cleanup_task.cancel()


app = FastAPI(title="HomeLab Monitoring", lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": "Données invalides"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com", "https://invest.example.com"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Cookie"],
    allow_credentials=True,
)


# Middleware d'authentification
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Routes publiques
    public_paths = ["/", "/api/auth/login", "/api/auth/check"]
    if request.url.path in public_paths or request.method == "OPTIONS":
        return await call_next(request)
    
    # Vérifier auth
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.cookies.get("sfauth")
    
    if token:
        payload = verify_token(token)
        if payload:
            request.state.user = payload["sub"]
            return await call_next(request)
    
    return JSONResponse(status_code=401, content={"detail": "Non authentifié"})


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def login(request: Request, data: LoginRequest):
    """Authentification et retour du token JWT"""
    client_ip = _client_ip(request)
    if _global_limit_reached():
        logger.warning("Plafond global d'échecs de connexion atteint")
        _alert_discord()
        return JSONResponse(status_code=429, content={"detail": "Trop de tentatives. Réessayez dans une minute."})
    if not _check_rate_limit(client_ip):
        logger.warning(f"Rate limit dépassé pour login depuis {client_ip}")
        return JSONResponse(status_code=429, content={"detail": "Trop de tentatives. Réessayez dans une minute."})
    # bcrypt prend ~0,2 s : hors de la boucle, sinon chaque auth_request attend (2 à la fois au plus)
    async with _bcrypt_slots:
        valid = await asyncio.to_thread(verify_password, data.username, data.password)
    if not valid:
        _login_failures.append(time.time())
        logger.warning(f"Échec d'authentification pour '{data.username}' depuis {client_ip}")
        return JSONResponse(status_code=401, content={"detail": "Identifiants incorrects"})
    
    token = create_token(data.username)
    response = JSONResponse(content={
        "status": "ok",
        "token": token,
        "username": data.username
    })
    response.set_cookie(
        key="sfauth",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400 * 7,
        path="/",
        domain=".example.com"
    )
    return response


@app.get("/api/auth/check")
async def check_auth(request: Request):
    """Vérifier si le token est valide"""
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.cookies.get("sfauth")
    
    if token:
        payload = verify_token(token)
        if payload:
            return {"authenticated": True, "username": payload["sub"]}
    
    return JSONResponse(status_code=401, content={"authenticated": False})


@app.post("/api/auth/logout")
async def logout():
    """Déconnexion"""
    response = JSONResponse(content={"status": "ok"})
    # Supprimer le cookie sur les 2 domaines possibles (ancien sans dot, nouveau avec dot)
    response.delete_cookie("sfauth", path="/", domain=".example.com")
    response.delete_cookie("sfauth", path="/", domain="example.com")
    response.delete_cookie("sfauth", path="/")
    return response


@app.get("/")
async def health():
    return {"status": "ok", "service": "monitoring-api", "version": "3.0.0"}


@app.get("/api/system")
async def get_system():
    """Métriques temps réel (depuis le cache mémoire, réponse instantanée)."""
    data = collector.get_current()
    if not data or "timestamp" not in data:
        return JSONResponse(
            content={"status": "loading", "message": "Collecting initial data...", "containers": []},
            headers={"Cache-Control": "no-store"}
        )
    return JSONResponse(content=data, headers={"Cache-Control": "no-store"})


@app.get("/api/history")
async def get_history(period: str = "1h"):
    """Historique des métriques agrégées."""
    valid = {"1h", "6h", "24h", "7d", "30d"}
    if period not in valid:
        return {"error": f"Invalid period. Use: {', '.join(sorted(valid))}"}
    return db.get_history(period)


@app.get("/api/containers")
async def get_containers():
    """Liste des conteneurs Docker."""
    data = collector.get_current()
    containers = data.get("containers", [])
    return {"count": len(containers), "containers": containers}


# ── SpeedTest (lancement manuel uniquement) ──

@app.post("/api/speedtest/run")
async def run_speedtest(target: str):
    """Lance un speedtest (host ou vpn). Retourne immediatement."""
    return speedtest.run_test(target)


@app.get("/api/speedtest/status")
async def speedtest_status():
    """Statut et resultats des speedtests."""
    return speedtest.get_status()

