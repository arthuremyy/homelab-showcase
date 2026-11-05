# Standard d'une application maison

Modèle suivi par Job Radar et Budget : le reprendre pour toute nouvelle
application. Exemple le plus récent et complet : [www/budget/](../../www/budget/).

## Structure
```
www/<app>/
  Dockerfile              python:3.12-slim, COPY backend/ + frontend/, HEALTHCHECK sur /api/<app>/health
  README.md               doc de l'application (gabarit : documentation.md)
  backend/
    app.py                FastAPI : lifespan (db.init + scheduler), middleware JWT, routers, sert frontend/
    config.py             dataclass Settings lue dans l'environnement
    db.py                 SQLite WAL, schéma + migrations idempotentes (marquées dans une table meta)
    routers/  services/  clients/
    test_*.py             tests purs, sans réseau
  frontend/
    index.html            charge /assets/ui/ui.css, services.js, shell.js (design system)
    assets/{css,js,ui}    ui/ = copie générée par scripts/sync-ui.sh
  tests/                  xss.mjs, puis e2e.mjs (jsdom), overflow.mjs et shoot.mjs (playwright)
  data/                   volume : base SQLite (+ secrets propres), hors git
```

## Règles communes
- **Réseau** : aucun port publié, réseau `web`, joint par nginx-proxy-local (vhost HTTPS + `auth_request`).
- **Auth** : le middleware revérifie le JWT `sfauth` (cookie ou Bearer) sur `/api/*`, sauf
  `/api/<app>/health` ([auth.md](../auth.md)).
- **Source de vérité unique** et données dérivées recalculables ; changer une règle de calcul ⇒ bumper
  une version stockée en `meta` et recalculer au démarrage.
- **Fonctions de calcul pures** (sans base ni réseau) dans `services/`, couvertes par `test_*.py`.
- **API** : données métier en body JSON (Pydantic), jamais en query param ; erreurs en `{"detail": …}`.
- **Tâches de fond** en boucles asyncio dans le conteneur (pas de cron hôte), chaque tour protégé par
  `try/except` pour qu'une erreur réseau ne tue pas la boucle.
- **Logs** : logger `httpx` en WARNING si l'app appelle un webhook ou une API à clé (sinon l'URL fuit).
- **Frontend** : modules ES natifs, aucun framework ni CDN ; **`esc()` obligatoire** sur tout HTML
  injecté ; CSS sur les jetons du [design system](../../www/_ui/README.md) uniquement ; vérifié de 320 à
  1440 px sans débordement horizontal ; `Cache-Control: no-cache` sur les fichiers statiques.
- **Discord** : un salon par domaine ([discord.md](../discord.md)) ; une notification n'est
  envoyée que s'il y a quelque chose à dire, dédoublonnée.
- **Sauvegarde** : base ajoutée à `backup.sh` (`dump_db`), conteneur critique ajouté à `heartbeat.sh`.
- Tests qui n'agissent jamais sur des systèmes réels (écritures bloquées au niveau réseau).

