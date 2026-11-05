# dashboard-api — authentification et métriques

Conteneur `dashboard-api`, port interne **8000**, image construite depuis `backend/` (code copié au build). Toutes les applications dépendent de
lui pour l'auth : voir [auth.md](../docs/auth.md).

| Fichier | Rôle |
|---|---|
| [app.py](app.py) | `/api/auth/login|check|logout` (limite de tentatives : voir auth.md), `/api/system`, `/api/history`, `/api/containers`, `/api/speedtest/run|status` ; sauvegarde des métriques toutes les 30 s, purge à 30 jours |
| [auth.py](auth.py) | JWT (création, vérification) + mot de passe (bcrypt uniquement) |
| [metrics.py](metrics.py) | Collecteur en thread : CPU, RAM, disques, réseau (`/proc/1/net/dev`), conteneurs Docker, températures |
| [database.py](database.py) | SQLite WAL `/data/metrics.db` (= `www/dashboard/data/metrics.db`), historique agrégé |
| [speedtest_runner.py](speedtest_runner.py) | Test de débit avec Ookla CLI |

Variables : `JWT_SECRET`, `ADMIN_PASSWORD_HASH`, `HOST_HOSTNAME=server`, `TZ`, `DOCKER_HOST`.

## Limites de connexion
5 essais / 60 s par client (IPv6 comptée par `/64`) et plafond global de 20 échecs / 60 s, avec alerte Discord
(`DISCORD_WEBHOOK_HEALTH`, 1 par 30 min). Pendant le plafond, toute connexion reçoit 429 ; les sessions ouvertes continuent.
En mémoire : remises à zéro au redémarrage du conteneur.
Vérification bcrypt hors de la boucle asyncio (2 à la fois) : une rafale de connexions ne fige pas `/api/auth/check`.

## Règles à ne pas casser
- **`pid: "host"`** obligatoire : `metrics.py` lit `/proc/1/net/dev` pour les interfaces réseau de l'hôte.
- **Pas de socket Docker monté** : Docker est joint via
  `DOCKER_HOST=tcp://docker-proxy:2375`. `docker-proxy` (tecnativa/docker-socket-proxy) est le seul à
  monter `/var/run/docker.sock` (`:ro`) et filtre l'API : `CONTAINERS=1`, `INFO=1`, `IMAGES=1` (sinon
  `c.image.tags` → 403 et liste vide), `NETWORKS`,
  `VOLUMES`, `AUTH`, `SECRETS`, `SWARM`, `SERVICES`, `TASKS`, `NODES` à 0.
