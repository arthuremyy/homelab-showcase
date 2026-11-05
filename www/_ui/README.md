# Design system commun (`www/_ui/`)

Une barre latérale et un design system partagés par les applications maison :
dashboard (accueil, Monitoring, Capital), Job Radar, Budget. Aperçu de tous les composants : [kitchen-sink.html](kitchen-sink.html)
(ouvrable en `file://`).

Style : sobre, dense, type SaaS ; filets 1 px, **une seule couleur d'accent**, clair et sombre ;
**aucun dégradé, halo, lueur, inclinaison ni emoji** ; animations ≤ 150 ms.

## Fichiers
| Fichier | Rôle |
|---|---|
| [tokens.css](tokens.css) | Jetons : couleurs clair/sombre, `--chart-1…8`, typo, rayons, espacements |
| [base.css](base.css) · [components.css](components.css) | Reset, typo ; `.btn` `.input` `.select` `.card` `.kpi` `.meter` `.badge` `.dot` `.tabs` `.segmented` `.table` `.modal` `.drawer` `.toast` `.notice` `.empty` `.grid-*` `.stack` |
| [shell.css](shell.css) · [shell.js](shell.js) | Barre latérale (`sf-*`), barre de page `.sf-pagebar`, contenu `.sf-content`, icônes `SF.icon()` |
| [services.js](services.js) | **Manifeste unique** des services (`window.SF_SERVICES`) : la barre et l'accueil en sont générés |

## Règles
- **Source unique ici.** [scripts/sync-ui.sh](../../scripts/sync-ui.sh) concatène les CSS en `ui.css` et copie
  le tout dans `*/assets/ui/` (dashboard, job-radar, budget). **Ne jamais éditer les copies.**
  Après sync : le dashboard est à jour aussitôt (volume) ; **Job Radar et Budget doivent être
  rebuildés**, sinon leur barre reste l'ancienne.
- Une page interne charge dans `<head>` : `/assets/ui/ui.css`, `/assets/ui/services.js`,
  `/assets/ui/shell.js` (script classique, **pas `defer`** : il pose thème et repli avant le rendu), puis
  `<header class="sf-pagebar">` + `<main class="sf-content">`. Sa propre CSS n'utilise **que les jetons**
  (`var(--…)`), jamais de couleur en dur.
- Entrée de `services.js` : `kind` `internal` (app maison, même onglet) / `external` (service tiers, nouvel
  onglet) / `home` ; `scope` `vpn` ou `public` ; `newTab` force un nouvel onglet ; `container` = pastille d'état.
  Nouvelle icône : l'ajouter à l'objet `P` de `shell.js`.
- Chaque application garde son domaine : **pas d'iframe** (`X-Frame-Options DENY`). Naviguer recharge la page.
- Préférences en **cookies sur `.example.com`** (`sf_theme`, `sf_nav`, `sf_ext`) : elles suivent
  l'utilisateur d'un sous-domaine à l'autre, ce que `localStorage` ne permet pas.
- La barre ne grise pas les services VPN depuis une page `*.example.com` (Local Network Access de
  Chrome) ; la sonde `https://dashboard.example.com/assets/ui/probe.svg` ne sert que hors domaine.
- Graphiques : couleurs lues par `SF.cssVar('--chart-1')` et réappliquées sur l'évènement `sf-themechange`.
- Cache : changer la version `?v=` dans les pages si un navigateur garde l'ancienne copie.
