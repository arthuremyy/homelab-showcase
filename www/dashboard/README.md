# Dashboard — accueil, Monitoring, front de Capital

Fichiers statiques servis par **nginx-dashboard** (`www/dashboard/` monté en volume : effet immédiat,
pas de rebuild). Routage, ports 80 public / 8082 VPN : [nginx.md](../../docs/nginx.md).
API : [dashboard-api](../../backend/README.md) et [capital-control](../capital-control/README.md).
Design system commun : [www/_ui](../_ui/README.md).

| Fichier | Rôle |
|---|---|
| [login.html](login.html) | Connexion **publique** (`example.com`) ; `?redirect=` limité aux chemins locaux et sous-domaines `https://*.example.com` ; `?logout=1` |
| [index.html](index.html) + [assets/js/home.js](assets/js/home.js) | Accueil `dashboard.example.com` (VPN) : indicateurs serveur, applications et services générés depuis `services.js`, état via `GET /api/system` |
| [monitoring.html](monitoring.html) + [assets/js/monitoring.js](assets/js/monitoring.js) | `monitoring.example.com` (VPN) : 4 graphiques Chart.js, polling 1 s (5 s après erreur), **pause onglet masqué**, speedtest |
| [capital.html](capital.html) + [assets/js/capital/](assets/js/capital/) | `capital.example.com` (VPN) : onglets Vue d’ensemble, PEA, Bitcoin, PEE, Mouvements ; modules ES `main.js` (routeur), `api.js` (401 → login), `state.js`, `forms.js` (mouvement, pointage, avis Natixis), `chart.js` (courbe SVG), `ui.js`, `fmt.js`, `views/*.js` ; aucune bibliothèque |
| [assets/js/auth-guard.js](assets/js/auth-guard.js) | Vérifie le cookie au chargement, `window.authFetch` (`credentials: 'include'`), déconnexion |
| [assets/css/](assets/css/) | `home.css`, `monitoring.css`, `capital.css` : mise en page propre, **uniquement sur les jetons** |
| `assets/ui/` | **Copie générée** du design system : ne pas éditer, voir [www/_ui](../_ui/README.md) |
| `data/` | `metrics.db` de dashboard-api (sauvegardée), jamais servi (`/data/` → 404) |

- **`esc()` obligatoire** sur tout HTML injecté.
- Graphiques : couleurs `--chart-*` relues sur `sf-themechange` (Monitoring) ; la courbe de Capital est en SVG stylé par CSS, le thème s'applique seul.
