"""
Module d'authentification JWT pour HomeLab
"""
import jwt
import os
import time
import bcrypt as _bcrypt
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

# Config (secrets chargés depuis les variables d'environnement)
SECRET_KEY = os.environ.get("JWT_SECRET")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET non défini dans l'environnement")
TOKEN_EXPIRY = 86400 * 7  # 7 jours

# Utilisateurs autorisés (hash chargé depuis l'env)
ADMIN_HASH = os.environ.get("ADMIN_PASSWORD_HASH")
if not ADMIN_HASH:
    raise RuntimeError("ADMIN_PASSWORD_HASH non défini dans l'environnement")
USERS = {
    "admin": ADMIN_HASH
}

def verify_password(username: str, password: str) -> bool:
    """Vérifie les identifiants (bcrypt uniquement)."""
    if username not in USERS:
        return False
    stored = USERS[username]
    if not stored.startswith(("$2b$", "$2a$", "$2y$")):
        return False
    return _bcrypt.checkpw(password.encode(), stored.encode())


def create_token(username: str) -> str:
    """Crée un token JWT"""
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_EXPIRY
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def verify_token(token: str) -> dict | None:
    """Vérifie et décode un token JWT"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def require_auth(request: Request):
    """Middleware: vérifie l'authentification sur les routes protégées"""
    # Routes publiques (pas besoin d'auth)
    public_paths = ["/", "/api/auth/login", "/api/auth/check"]
    if request.url.path in public_paths:
        return

    # Vérifier le header Authorization
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = verify_token(token)
        if payload:
            request.state.user = payload["sub"]
            return

    # Vérifier le cookie sfauth
    token = request.cookies.get("sfauth")
    if token:
        payload = verify_token(token)
        if payload:
            request.state.user = payload["sub"]
            return

    raise HTTPException(status_code=401, detail="Non authentifié")
