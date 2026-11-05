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

## Choix de sécurité

- Une seule entrée publique (la page de connexion) ; les applications sont réservées au VPN.
- `auth_request` nginx, puis nouvelle vérification du JWT par chaque application.
- Socket Docker jamais monté dans une application : passage par un proxy à droits limités, sur un réseau interne.
- Limitation des tentatives de connexion ; secrets uniquement en variables d'environnement.
- Conteneurs sans droits root ni capacités quand c'est possible, images épinglées.

## Lancer

```bash
cp docker/.env.example docker/.env   # puis remplir JWT_SECRET et ADMIN_PASSWORD_HASH
cd docker && docker compose up -d --build
```

La page de connexion répond sur `http://127.0.0.1:8080`. Les redirections de production visent
`example.com` et un accès HTTPS par sous-domaine : pour une démonstration complète, adapter les
configurations de `docker/nginx-proxy/`.
