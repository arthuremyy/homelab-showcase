# Homelab showcase

Applications auto-hébergées et leur infrastructure Docker, publiées à titre de démonstration.
Le code provient d'un serveur personnel en production ; domaines, identités et données sont fictifs.

## Applications

| Application | Rôle | Pile |
|---|---|---|
| `www/budget` | Comptes, charges fixes détectées, prévision de fin de période | FastAPI, SQLite, JS natif |
| `www/capital-control` | Portefeuille, performance, alertes, briefing assisté par LLM | FastAPI, SQLite |
| `www/job-radar` | Collecte multi-sources, déduplication et score d'offres d'emploi | FastAPI, SQLite |
| `www/dashboard` + `backend` | Connexion commune, accueil, supervision système | FastAPI, nginx, Chart.js |
| `www/_ui` | Design system et navigation partagés | CSS, JS |

Chaque dossier a son README : modèle de données, règles métier, tests.

## Choix de sécurité

- Une seule entrée publique (la page de connexion) ; les applications sont réservées au VPN.
- `auth_request` nginx, puis nouvelle vérification du JWT par chaque application.
- Socket Docker jamais monté dans une application : passage par un proxy à droits limités, sur un réseau interne.
- Limitation des tentatives de connexion ; secrets uniquement en variables d'environnement.
- Conteneurs sans droits root ni capacités quand c'est possible, images épinglées.

## Documentation

| Sujet | Page |
|---|---|
| Architecture réseau, deux entrées, ports | [docs/architecture.md](docs/architecture.md) |
| Authentification commune | [docs/auth.md](docs/auth.md) |
| Reverse proxy nginx | [docs/nginx.md](docs/nginx.md) |
| Sauvegardes chiffrées et supervision | [docs/backups-monitoring.md](docs/backups-monitoring.md) |
| Gestion des secrets | [docs/secrets.md](docs/secrets.md) |
| DNS interne | [docs/dns.md](docs/dns.md) |
| Alertes Discord | [docs/discord.md](docs/discord.md) |
| Restauration et redémarrage | [docs/runbooks/](docs/runbooks/) |
| Standards d'application et de documentation | [docs/standards/](docs/standards/) |

Les scripts d'exploitation sont dans [scripts/](scripts/), le tunnel d'exemple dans
[docker/cloudflared/](docker/cloudflared/).

## Lancer

```bash
cp docker/.env.example docker/.env   # puis remplir JWT_SECRET et ADMIN_PASSWORD_HASH
cd docker && docker compose up -d --build
```

La page de connexion répond sur `http://127.0.0.1:8080`. Les redirections de production visent
`example.com` et un accès HTTPS par sous-domaine : pour une démonstration complète, placer un certificat dans
`docker/nginx-proxy/certs/` puis activer le proxy avec `docker compose --profile vpn up -d`.
