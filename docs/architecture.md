# Architecture

Un seul serveur Ubuntu, tout en Docker, avec un réseau bridge `web`. Les conteneurs se joignent par leur nom.

## Deux portes d'entrée

```
Internet (HTTPS) → Cloudflare Tunnel        aucun port ouvert sur le routeur
  └── example.com → nginx-dashboard:80      page de connexion uniquement

VPN Tailscale → DNS interne → nginx-proxy-local:443 (certificat wildcard, HTTP redirigé vers HTTPS)
  └── un vhost par service, protégé par auth_request
```

Un service réservé au VPN n'a aucune route dans le tunnel : c'est cette absence qui le rend inaccessible
depuis Internet. Le port interne de nginx-dashboard réservé au VPN n'est jamais ajouté au tunnel.

## Services

| URL | Conteneur:port | Vhost |
|---|---|---|
| dashboard. / monitoring. / capital.example.com | nginx-dashboard:8082 | `dashboard-vpn.conf` |
| budget.example.com | budget:8700 | `budget.conf` |
| jobs.example.com | job-radar:8400 | `jobs.conf` |
| adguard.example.com | adguard:3000 | `adguard.conf` |

| Conteneur interne | Rôle |
|---|---|
| `dashboard-api` (8000) | Authentification et métriques |
| `capital-control` (8100) | API Capital, servie sous `/api/capital/` par nginx-dashboard |
| `docker-proxy` (2375) | Seul à monter le socket Docker, sur un réseau interne partagé avec `dashboard-api` seul |

## Règles

- **Ports publiés sur l'hôte :** uniquement le proxy VPN (80, 443) et le DNS (53). Le compose de démonstration
  publie seulement la page de connexion, sur `127.0.0.1`.
- **Un seul cookie d'authentification**, revérifié par chaque application : [auth.md](auth.md).
- **Images épinglées** par version ou digest ; secrets uniquement en variables : [secrets.md](secrets.md).
- **Noms résolus à chaque requête** par nginx : un service absent ne bloque pas le proxy ([nginx.md](nginx.md)).
- **Code copié dans les images** : modifier une application exige de la reconstruire, sauf `www/dashboard/`, monté en volume.
- **`www/_ui/` est la source unique** du design system ; `scripts/sync-ui.sh` génère les copies.
- **`esc()` obligatoire** sur tout HTML injecté ; données métier en body JSON, jamais en paramètre d'URL.
