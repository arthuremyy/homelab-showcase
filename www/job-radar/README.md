# Job Radar — veille d'offres d'emploi cyber

`https://jobs.example.com` · conteneur `job-radar` · port interne **8400** · **Tailscale uniquement**
(vhost [jobs.conf](../../docker/nginx-proxy/conf.d/jobs.conf)). Suit le
[standard d'application](../../docs/standards/application.md). Base SQLite WAL `data/jobs.db`
(sauvegardée ; reconstructible par collecte, seuls les statuts du suivi et le profil sont irremplaçables).

## Source de vérité
La table **`offers`**. Les trois indices sont **dérivés** ([scoring.py](backend/services/scoring.py)),
entièrement recalculables, jamais écrits à la main. Changer le moteur ⇒ bumper `ENGINE_VERSION`, puis
rescore (onglet Réglages ou `POST /api/jobs/rescore`).

## Fichiers
| Fichier | Rôle |
|---|---|
| [backend/app.py](backend/app.py) | FastAPI, middleware JWT (`sfauth`), sert `frontend/` |
| [backend/db.py](backend/db.py) | Schéma, migrations, profil par défaut, requêtes `DEFAULT_QUERIES` (changer ⇒ bumper `QUERIES_SEED_VERSION`, les désactivations manuelles sont conservées) |
| [backend/sources/](backend/sources/) | `france_travail.py`, `adzuna.py`, `jooble.py` |
| [backend/services/scoring.py](backend/services/scoring.py) | Les 3 indices |
| [backend/services/dedupe.py](backend/services/dedupe.py) | Clés stricte et lâche |
| [backend/services/collector.py](backend/services/collector.py) | Collecte, upsert, péremption, alertes immédiates |
| [backend/services/actions.py](backend/services/actions.py) | Seuils de relance et groupes « À faire » (partagés par l'UI et le récap Discord) |
| [backend/services/scheduler.py](backend/services/scheduler.py) | Collecte toutes les `JOBS_COLLECT_HOURS` h (défaut 2) pour France Travail ; Adzuna et Jooble une fois par jour à 06:30 ; récap quotidien |
| [backend/routers/offers.py](backend/routers/offers.py) | `/overview`, `/list`, `/deck`, `/status`, `/followup`, `/todo`, `/stages`, `/collect`, `/rescore`, `/stats` |
| [frontend/assets/js/statuts.js](frontend/assets/js/statuts.js) | **Vocabulaire unique** (libellés, actions suivantes, confirmations) |
| [frontend/assets/js/views/sheet.js](frontend/assets/js/views/sheet.js) | Fiche d'offre, identique dans le deck et le tiroir |

## Les trois indices — pondération à ne pas casser
Le moteur privilégie les postes généralistes, qui ouvrent des portes, plutôt que les postes très spécialisés.

| Indice (affiché) | Nature | Rôle |
|---|---|---|
| Matching (« Pertinence ») | déterministe | La cible est la **cyber généraliste où le passé industriel est un plus**, pas « cybersécurité industrielle » |
| Portabilité (« Ouverture ») | déterministe | Ce poste ouvre-t-il ou referme-t-il des portes à 3-5 ans |
| Réussite (« Chances ») | heuristique | **Jamais une prédiction** ; seul indice où le passé industriel joue |

- OT pur **plafonné à `OT_MATCH_CAP` = 55**, ne domine jamais le classement.
- Un marqueur OT (`OT_TITLE_MARKERS`) ou automatisme (`LOCKIN_TITLES`) dans l'**intitulé** force
  `track=ot_pur`, même avec « cybersécurité » : « Ingénieur Cybersécurité Industrielle » est un poste OT.
- Intitulés commerciaux (`EXCLUDE_ROLE_TITLES`) hors périmètre.
- Comparaisons d'intitulés par `_pat()` (limites de mots), **jamais `in`** : `"mes" in title` matchait
  « systè**mes** et réseaux ».
- Plancher de salaire (`profile.salary_floor`) : haut de fourchette sous le plancher → −18 ; minimum
  ≥ 112 % du plancher → +6 ; **salaire absent → aucune pénalité** (44 % des offres cyber n'en affichent pas).
- Type de contrat : **le champ structuré de la source fait foi** ; déduction textuelle en dernier recours
  (« vous encadrerez des alternants » classait un CDI en alternance, −30).
- `xp_required` : le libellé de la source fait foi, regex sur la description en repli.

## Sources
| Source | Rythme | Contraintes |
|---|---|---|
| France Travail | `FREQUENT_SOURCES` | Seule source **vérifiable offre par offre** (`GET /offres/{id}` : 200 en ligne, 204 retirée — `check()`). OAuth2 `client_credentials` (jeton ~25 min, renouvelé 60 s avant). **5 départements max par recherche** (400 au-delà, `MAX_DEPTS_PER_QUERY`) ; `range` ≤ 149 ; seule source à rendre la **description intégrale**. `invalid_client` ⇒ vérifier que l'API « Offres d'emploi v2 » est souscrite à l'application |
| Adzuna | `DAILY_SOURCES`, 1 passe/jour | Palier Trial ~1000 appels/mois, **aucun en-tête de quota** : 1 appel par requête, pas de pagination (une requête de plus ≈ 30 appels/mois). `company` = souvent un job board ; `salary_is_predicted` = estimation, ignorée ; département en clair (`base.DEPT_BY_NAME`, `dept_from_text`) |
| Jooble | `DAILY_SOURCES`, 1 passe/jour | `POST fr.jooble.org/api/{JOOBLE_API_KEY}`. **500 requêtes au total** (plus = demande par courriel à Jooble) : chaque appel compté dans `meta.jooble_calls`, arrêt à `BUDGET` = 480 ; 1 page de 100 par requête, 3 requêtes. Surtout HelloWork et Free-Work. `snippet` = extrait ; `type` peu fiable (« Stage » sur des alternances) : le titre prime. Traitée comme republication |
| LinkedIn / Indeed | ❌ exclus | CGU anti-scraping + Cloudflare |
| APEC | ❌ retirée (2026-10-15) | Site derrière DataDome (403 depuis le 2026-10-01) : ne pas contourner |

- **« Actualiser maintenant »** (`POST /collect`) ne lance que `FREQUENT_SOURCES` (quota Adzuna) ;
  `collector.RUNNING` empêche deux passes simultanées d'une même source.
- **Dédup** : stricte = titre + entreprise + ville ; lâche = titre + **code département** (chaque source
  écrit la ville autrement), qui ne fusionne **que si un côté est une republication** (Adzuna, Jooble ou job board
  dans `company`, comparé en sous-chaîne : n'y mettre que des termes entiers et spécifiques).
- **Offre fantôme** (malus de 10 sur « Chances ») : offre vue pour la première fois il y a plus de `GHOST_DAYS` = 45 j, quelle que soit sa source.
- **Fraîcheur** :
  - France Travail : à chaque collecte, toute offre FT active non revue **et** toute offre du suivi
    (`TRACKED`, même déjà retirée) est revérifiée (`verify_france_travail`) ; une fiche FT ouverte est
    revérifiée en direct si non confirmée depuis `LIVE_CHECK_MIN` = 15 min. Les liens FT d'une offre
    retirée rendent 404 : c'est normal.
  - Autres sources : « retirée » après `MISSING_LIMIT` = 3 collectes sans la revoir **et**
    `MISSING_HOURS` = 24 h.
  - Filet global : toute offre non confirmée depuis `STALE_HOURS` = 72 h est retirée (`expire_stale`).
  - Retirée ⇒ hors « À trier » ; dans le suivi, badge « Annonce retirée ».
- `httpx` est en WARNING : en INFO il journalise les URL avec `app_key` Adzuna et le webhook Discord.
- Aucune source ne fournit de date limite de candidature ni de date de début : **ne pas les afficher**.

## Suivi des candidatures (modèle v2, `meta.status_model`)
`nouveau` → `ecarte` (passée au tri, exclue du suivi) · `vivier` → `candidate` → `entretien` → `offre` ·
terminées `refuse`, `sans_reponse`, `decline`.
- `pipeline.applied_at` posée **automatiquement** au passage en `candidate` ; elle alimente les relances
  sans saisie : `RELANCE_J` = 10, `SILENCE_J` = 21, `DORMANT_J` = 7 ([actions.py](backend/services/actions.py)).
- Jamais de code interne à l'écran : `vivier` = « À postuler », `candidate` = « Postulé »,
  `ecarte` = « Pas pour moi », `decline` = « Abandonnée ».

## Interface
Cinq onglets : **Aujourd'hui** (défaut, un seul appel `GET /overview`) · **À trier** (deck, `POST /deck`) ·
**Candidatures** (`POST /list`) · **Toutes les offres** (`POST /list`, pagination par 100) · **Réglages**.
- L'action principale suit le contexte (`suite(o)`) : relance due ⇒ « J'ai relancé », silence > 21 j ⇒
  « Sans réponse », annonce retirée dans « À postuler » ⇒ « Retirer » (groupe `retiree`).
- Carte du deck : six informations seulement (intitulé, entreprise, ville, salaire, expérience,
  contrat) ; le reste dans le dépliant. Geste : décision au-delà de 105 px. Raccourcis `←` `→` `↵` `D` `Z`.
- Design system commun ([www/_ui](../_ui/README.md)) ; **`esc()` obligatoire** sur tout HTML injecté.

## Notifications Discord
| Quand | Quoi |
|---|---|
| À chaque collecte | Offre **nouvelle** avec matching ≥ `alert_min` (défaut 85) ; jamais pour `lock_in_flag` |
| Chaque jour à `digest_hour` (défaut 08:00) | Nouvelles offres 24 h, relances dues, sans réponse, vivier dormant. **Rien n'est envoyé s'il n'y a rien à dire** |

Réglages dans le **profil** (`discord_webhook`, `alert_min`, `digest_hour`), modifiables sans redéploiement.
Webhook vide ⇒ repli sur `DISCORD_WEBHOOK_JOBS` ([notify.py](backend/services/notify.py)).

## Tests
```bash
cd www/job-radar
python3 backend/test_scoring.py                    # pondération anti-enfermement
node tests/xss.mjs                                 # échappement
JSDOM_PATH=/tmp/node_modules/jsdom SFAUTH="$TOKEN" node tests/e2e.mjs    # parcours réel (jsdom hors dépôt)
PLAYWRIGHT_PATH=/tmp/node_modules/playwright/index.mjs SFAUTH="$TOKEN" node tests/overflow.mjs   # 320 → 1920 px
PLAYWRIGHT_PATH=/tmp/node_modules/playwright/index.mjs SFAUTH="$TOKEN" node tests/shoot.mjs      # captures
```
