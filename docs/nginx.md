# nginx : deux instances


**Noms résolus à chaque requête** (`conf.d/00-resolver.conf`, `set $up_x …; proxy_pass $up_x;`) : un service absent ne donne qu'une erreur sur son site, et une recréation ne demande plus de reload. Modèle obligatoire pour tout nouveau vhost.

## nginx-proxy-local (entrée Tailscale)
- Seul conteneur à publier 80/443. Config : [nginx.conf](../docker/nginx-proxy/nginx.conf) +
  **un fichier par service** dans [conf.d/](../docker/nginx-proxy/conf.d/), certificat wildcard dans
  `docker/nginx-proxy/certs/` (renouvellement : [scripts/cert-renew-hook.sh](../scripts/cert-renew-hook.sh)).
- Modèle de vhost : copier [jobs.conf](../docker/nginx-proxy/conf.d/jobs.conf) (80 → 301 HTTPS ;
  443 avec `/_auth`, `auth_request`, `@login_redirect`, en-têtes `X-Real-IP` / `X-Forwarded-*` / `Cookie`,
  endpoint de santé sans auth).
- Après modification ou recréation d'un conteneur cible : `docker exec nginx-proxy-local nginx -t && docker exec nginx-proxy-local nginx -s reload`.

## nginx-dashboard (service compose `nginx`)
Config : [config/nginx-dashboard.conf](../config/nginx-dashboard.conf), fichiers statiques
`www/dashboard/` montés en volume (effet immédiat, sans rebuild). **Deux serveurs** :

| Port | Joint par | Sert |
|---|---|---|
| `:80` **public** | cloudflared (`example.com`) | `login.html`, `/assets/`, `/api/auth/*`  |
| `:8082` **VPN** | nginx-proxy-local (`dashboard-vpn.conf`) | accueil (`dashboard.`), `monitoring.html`, `capital.html` selon l'hôte ; `/api/capital/` → capital-control:8100 (timeout 180 s, briefing IA) ; `/api/` → dashboard-api:8000 |

- `proxy_set_header Cookie $http_cookie` dans les blocs `/api/` : nécessaire à l'auth par cookie.
- `listen 80 default_server` sur le bloc par défaut (plusieurs `server`).
- En-têtes de sécurité : `X-Frame-Options DENY`, `X-Content-Type-Options nosniff`,
  `CSP frame-ancestors 'none'`. **Pas** de HSTS `includeSubDomains` (Cloudflare gère HSTS).
- ⚠ **Fichier monté seul** (bind-mount de fichier) : un éditeur crée un nouvel inode, `nginx -s reload`
  relit l'ancien. Après modification : `docker restart nginx-dashboard`.
- Après recréation de `dashboard-api` ou `capital-control` : `docker exec nginx-dashboard nginx -s reload`.
