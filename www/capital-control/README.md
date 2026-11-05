# Capital Control — investissements PEA, Bitcoin, PEE (v3)

API `capital-control` (service compose **`capital-api`**), port interne **8100**, servie sous
`https://capital.example.com/api/capital/` par nginx-dashboard:8082 (Tailscale). **Ne sert pas le
frontend** : celui-ci est dans [www/dashboard](../dashboard/README.md) (`capital.html` +
`assets/js/capital/`). Résumé repris par [Budget](../budget/README.md) (`GET /api/portfolio`, clés
`total_value`, `total_invested`, `pnl_eur`, `pnl_pct`, `day_change_*`, `position_count` : à conserver).
Base `data/capital.db` (WAL, sauvegardée).

## Modèle
- **Trois comptes fixes** (table `accounts`) : `PEA` et `CRYPTO` (Trade Republic), `PEE` (Natixis
  Interépargne). L'établissement fait foi ; l'application en est le miroir, contrôlé par **pointage**.
- **Source de vérité : `transactions`** (buy / sell / dividend / fee), groupées par (actif, compte).
  Positions **dérivées** ([valuation.py](backend/services/valuation.py)). ⛔ Jamais d'écriture directe
  de position. Tables `positions` (legacy, lecture seule) et migrations : `meta.migrated_v2`, `migrated_v3`.
- PEE : `amount` = versé par moi, `employer_amount` = abondement brut, `social_tax` = prélèvements
  sociaux, `available_on` = date de disponibilité (lots consommés du plus ancien au plus récent).
  **Gain = valeur − versé** (l'abondement net est un gain) ; PRU = (versé + abondement net) / parts.
- `source` : `manuel`, `pdf` (avis Natixis, dédoublonné par `external_id`), `pointage` (rattrapage,
  date et prix à préciser), `reprise` (soldes de départ, PRU estimé).

## Pointage ([checks.py](backend/services/checks.py), table `checks`)
- Manuel (PEA, Bitcoin) : quantités et valeurs recopiées depuis l'app → écart de **quantité** (un
  mouvement manque : rattrapage proposé) ou de **cours** (source de prix divergente : signalé, rien
  à corriger). Tolérances en tête de fichier.
- PEE : import de l'**avis d'opération PDF** ([natixis.py](backend/services/natixis.py), `pypdf`) :
  versements ajoutés, puis la « situation des avoirs » sert de pointage par fonds et par date de
  disponibilité ; la valeur de part est comparée à notre cours Yahoo du même jour.
- État d'un compte : `ok`, `a_pointer` (dernier pointage > 31 j, 92 j pour le PEE), `ecart`.

## Fichiers
| Fichier | Rôle |
|---|---|
| [backend/app.py](backend/app.py) | FastAPI, middleware JWT (`sfauth` ou Bearer), routers, lifespan (migrations + scheduler) |
| [backend/db.py](backend/db.py) | Schéma v3, comptes, migrations idempotentes |
| [backend/routers/](backend/routers/) | `accounts` (comptes, pointage, import PEE) `transactions` `portfolio` `assets` `alerts` `briefing` |
| [backend/services/valuation.py](backend/services/valuation.py) | Positions, versé / abondement / coût, lots, état de pointage, plafond PEA |
| [backend/services/history.py](backend/services/history.py) | Historique **recalculé** depuis les transactions et les cours passés (`portfolio_snapshots`) |
| [backend/services/pricing.py](backend/services/pricing.py) | Prix → `prices_last` (crypto CoinGecko, actions et fonds Yahoo, conversion EUR) |
| [backend/services/alerts_engine.py](backend/services/alerts_engine.py) | Alertes de prix (seuil, variation du jour) avec délai de répit |
| [backend/ai/briefing.py](backend/ai/briefing.py) · [llm.py](backend/ai/llm.py) | Briefing IA hebdomadaire (Claude `ANTHROPIC_MODEL`, repli Gemini) ; actualités via [providers/news.py](backend/providers/news.py) |

## Tâches de fond (aucun cron hôte)
| Tâche | Rythme |
|---|---|
| Prix | crypto 90 s ; actions et fonds 5 min marché ouvert, 1 h sinon |
| Alertes | à chaque passe de prix → Discord #new-financing |
| Historique | au démarrage, 23:50, et 2 s après toute modification de mouvements |
| Briefing IA | hebdomadaire, `BRIEFING_DAY` (0 = lundi) à `BRIEFING_HOUR` (07:30) → Discord |
| Récap hebdo | dimanche 19:00 → Discord, avec les comptes à pointer |

## Règles
- Données métier dans un **body JSON Pydantic** (ou multipart pour le PDF), jamais en query param
  (les query params finissent dans les logs nginx). Query params : filtres de lecture seulement.
- Aucune donnée réelle (montants, relevés) dans le dépôt : tests sur chiffres fictifs.
- Front : **`esc()` obligatoire** sur tout HTML injecté ; `api.js` renvoie au login sur 401.
- Briefing long : `/api/capital/` a un `proxy_read_timeout` de 180 s dans nginx-dashboard.
- Logger `httpx` en WARNING ([app.py](backend/app.py)) : sinon l'URL du webhook Discord finit dans les logs.

Variables : `JWT_SECRET`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `GEMINI_API_KEY`,
`DISCORD_WEBHOOK_FINANCE`, `BRIEFING_DAY`, `BRIEFING_HOUR` ; secrets propres dans `www/capital-control/.env`.

## Tests
```bash
docker run --rm -v "$PWD/www/capital-control/backend":/app -w /app docker_capital-api python test_capital.py
```
`nginx -s reload` dans **nginx-dashboard**).
