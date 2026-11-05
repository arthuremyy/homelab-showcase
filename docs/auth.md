# Authentification commune (`sfauth`)

Un seul compte (admin), un seul cookie pour toutes les applications maison et les services VPN.
Code : [backend/app.py](../backend/app.py), [backend/auth.py](../backend/auth.py).

## Parcours
1. `POST /api/auth/login` (dashboard-api) : vérifie le hash bcrypt (`ADMIN_PASSWORD_HASH`), limite à
   **5 tentatives / 60 s par IP** (en mémoire), pose le cookie **`sfauth`** : JWT HS256 signé par
   `JWT_SECRET`, `HttpOnly`, `Secure`, `SameSite=Lax`, `Domain=.example.com`, 7 jours.
2. nginx protège chaque page par `auth_request` → `GET http://dashboard-api:8000/api/auth/check`
   (en-tête `Cookie` transmis). 401 → `https://example.com/login.html?redirect=<url>`.
3. Chaque application **revérifie** le JWT dans un middleware (défense en profondeur) avec le même
   `JWT_SECRET` : cookie `sfauth` ou en-tête `Authorization: Bearer`.
4. Déconnexion depuis n'importe quel sous-domaine : `https://example.com/login.html?logout=1`.

`login.html` n'accepte en `?redirect=` qu'un chemin local ou un sous-domaine `https://*.example.com`.

## Règles
- Le nom du cookie est **`sfauth` partout**. Un décalage casse la validation.
- Jeton en cookie seulement, **jamais en `localStorage`** (XSS).
- Appel serveur à serveur (ex. Budget → Capital) : JWT de service court signé par `JWT_SECRET`,
  en `Authorization: Bearer` (exemple : [www/budget/backend/routers/misc.py](../www/budget/backend/routers/misc.py)).
- Jeton de test pour les scripts et tests playwright :
  `docker exec dashboard-api python3 -c "from auth import create_token; print(create_token('admin'))"`.
- Changer le mot de passe : générer le hash
  `docker exec dashboard-api python3 -c "import bcrypt; print(bcrypt.hashpw(b'MOT_DE_PASSE', bcrypt.gensalt()).decode())"`,
  le reporter dans `ADMIN_PASSWORD_HASH` (`docker/.env`), recréer `dashboard-api`.
