# Budget — application financière principale

Conteneur `budget`, port interne **8700** · **Tailscale uniquement**
(vhost [budget.conf](../../docker/nginx-proxy/conf.d/budget.conf), `auth_request` + JWT revérifié).
Premier lien de la barre latérale. Suit le [standard d'application](../../docs/standards/application.md).

Comptes bancaires synchronisés (Enable Banking), catégories, **fixes** (revenus/charges qui
reviennent chaque mois), reste à vivre, Livret A estimé, coût du découvert. Capital (investissements)
reste un service distinct, résumé dans la carte « Investissements ».

## Source de vérité
La table **`operations`** (banque ou saisie manuelle). Contrepartie, catégorie, fixes, reste à vivre,
Livret A sont **dérivés** ; seule une catégorie posée à la main (`category_locked`) n'est jamais recalculée.

## Fichiers
| Fichier | Rôle |
|---|---|
| [backend/clients/enablebanking.py](backend/clients/enablebanking.py) | API Enable Banking (DSP2), JWT RS256 signé par `data/eb_private.pem`, `kid` = `EB_APP_ID` |
| [backend/services/sync.py](backend/services/sync.py) | Upsert idempotent (`ext_id`) ; opérations en attente (PDNG) **remplacées** à chaque passe ; solde « disponible » (ITAV/XPCD) prioritaire ; opération sans référence (`h:`) remplacée par sa version référencée (`eb:`, même jour/montant, contrepartie égale ou tronquée au mot près) ; opération en attente ignorée si déjà annoncée par cette version courte ; opération en attente disparue avant de revenir comptabilisée gardée 7 j au plus (meta `vanished_pending`, `still_vanished`) pour reconnaître les fixes réglés — jamais comptée dans les totaux ; `reparse_all()` + `dedupe_unreferenced()` au démarrage |
| [backend/services/categorize.py](backend/services/categorize.py) | **Pur.** `parse_label` : contrepartie lue dans le libellé bancaire ; `match` : catégorie |
| [backend/services/recurring.py](backend/services/recurring.py) | **Pur.** Détection des fixes (propose seulement) |
| [backend/services/forecast.py](backend/services/forecast.py) | **Pur.** Totaux du mois, fixes attendus, reste à vivre, point bas, coût du découvert |
| [backend/services/views.py](backend/services/views.py) | Lectures composées (fixes + présence, Livret A, contreparties) |
| [backend/services/scheduler.py](backend/services/scheduler.py) | Synchro `SYNC_HOURS` 07:00/12:00/18:00/23:00 (+1 nouvel essai 15 min après un échec) ; contrôle 09:00 → Discord #new-financing |
| [backend/db.py](backend/db.py) | Schéma, migrations, catégories système `SEED` (mots-clés) |
| [frontend/assets/js/views/](frontend/assets/js/views/) | 4 onglets : `mois` (Ce mois), `operations`, `fixes`, `reglages` |

## « Ce mois » — chiffres affichés
**Mois en cours = période d'un salaire au suivant** (`forecast.pay_period`) : du dernier versement du
plus gros revenu fixe à la veille du même jour le mois suivant ; prolongée si le salaire est en retard ;
mois calendaire si aucun salaire depuis 45 j. Salaire et loyer tombent en fin de mois : le mois calendaire
comparait les dépenses au salaire arrivé à sa toute fin. Mois passés, tendance 6 mois et « habituel »
restent calendaires.

Ordre de lecture (mobile identique) : une seule alerte, la plus grave → chiffre clé → dépenses → prochains
fixes → 6 derniers mois → Livret A, Découvert, Investissements. Calculs dans
[forecast.py](backend/services/forecast.py) (purs, testés).

| Chiffre | Définition |
|---|---|
| **Dépensable** (chiffre clé) | `spendable` : min(point bas de la période, reste à vivre − dépenses courantes de la période) ; dit lequel des deux limite |
| Reste à vivre | `envelope` : revenus fixes − charges fixes ; le salaire compte pour son **montant réellement reçu** en début de période |
| Avant le prochain salaire | `remaining` : solde + fixes encore attendus dans la période (`pending_in_period` : échéance dans la période, réglé par une opération d'au plus 20 j avant) |
| Rythme | dépenses courantes (hors fixes) face au reste à vivre × jours écoulés / durée de la période |
| « habituel » | `views.category_avg` : moyenne de la catégorie sur les 3 mois précédents ayant des opérations |
| « à classer » | catégorie « Divers » (repli de la catégorisation) ou sans catégorie ; filtre dans Opérations |

Dépensable en orange sous le seuil `low_balance` (Réglages › Alertes ; 0 = jamais). Mois passé : le chiffre
clé devient entrées − dépenses.

## Lecture des libellés bancaires
La banque **ne transmet pas la contrepartie** à Enable Banking : `parse_label` la lit dans le libellé
(`CARTE X…`, `PAIEMENT CARTE DU`, `PRELEVEMENT … DE:`, `VIR … DE:/POUR:`, `VIREMENT DECLIC` = épargne
automatique, devise/pays après le montant = étranger).

Ordre de catégorisation : verrou manuel → règle utilisateur → frais/retrait/épargne (virement vers ou
depuis **soi-même** = nom du titulaire du compte) → mot-clé système → étranger = Voyages → particulier
= « Remboursements reçus » / « Virements à des proches » → Revenus (entrée) / Divers (sortie).
Comparaisons **par mots entiers** (`CAF` ≠ `CAFE`), le mot-clé le plus long gagne.

- Changer la lecture des libellés ⇒ bumper `PARSE_VERSION` (sync.py) : au démarrage, contreparties
  relues et catégories recalculées (sauf verrouillées).
- Nouvelles catégories système ⇒ bumper `SEED_VERSION` (db.py) ; une catégorie créée ou renommée par
  l'utilisateur n'est jamais touchée.
- « Remboursements reçus » est de nature **dépense** : un virement d'ami réduit les dépenses, il ne
  gonfle pas les revenus.

## Fixes
- Clé d'un fixe = 4 premiers mots significatifs de la contrepartie + sens (`key_of`). `match_key` =
  contrepartie qui le règle (défaut : sa propre clé).
- Détection : même clé, montants regroupés à ±15 %, ≥ 2 mois, majorité d'écarts de 20-40 j, vu depuis
  < 45 j ; libellé vu plus de 2,2 fois par mois = commerce, pas un fixe ; retraits exclus.
  Deux montants distincts sous un même libellé (box + mobile) ⇒ deux fixes, même `match_key`.
  Suggestion à ±15 % d'un fixe connu du même libellé (hors forfait qui déplace la médiane) : pas reproposée.
- Réglé ce mois-ci : fixe seul sur sa contrepartie ⇒ réglé dès qu'une opération passe, quel que soit
  le montant ; plusieurs fixes sur une contrepartie ⇒ appariement par montant, ou un virement pour
  tous si les sommes concordent.
- Opération sans contrepartie lisible (en attente « VIR INSTANTANE EMIS » du loyer) : rattachée dans
  « Ce mois » au fixe non réglé du même sens à ±15 % (`attach_anonymous`), avec sa catégorie habituelle.
- **Rattacher** (Ce mois › Prochains fixes) : l'utilisateur désigne l'opération qui règle un fixe non
  reconnu (`operations.recurring_id`, `POST /recurring/link`). Libellé lisible ⇒ devient son `match_key`
  (reconnu seul les mois suivants) ; montant retenu au choix ; catégorie habituelle posée. Le lien suit
  l'opération en attente recréée à chaque passe et la version référencée qui remplace un `h:`.
- `missing` : fixe absent de **tout** le mois précédent (abonnement résilié, promo finie).

## Livret A
Pas lisible par la banque : solde connu à une date (Réglages, `settings.livret`) + virements vers/depuis
soi-même et « Déclic seuil ». Intérêts du 31/12 non vus : recaler le solde en janvier.

## Enable Banking — règles à ne pas casser
- Mode **restricted** gratuit : seuls les comptes reliés dans la **console Enable Banking** sont lisibles.
- **4 lectures/jour/compte sans l'utilisateur** (DSP2) : ne pas ajouter de passe automatique. La synchro
  manuelle envoie `Psu-Ip-Address`/`Psu-User-Agent` (utilisateur présent, hors quota).
- Consentement ≤ 180 j (durée max lue chez la banque) ; retour sur `/api/budget/bank/callback`
  (redirect URL déclarée dans la console EB) ; « Renouveler l'accès » dans Réglages.
- Un nouveau consentement redonne de **nouveaux uid de compte** : même compte reconnu par `identification_hash`
  (colonne `ident_hash`, repli sur la fin d'IBAN si unique), historique rattaché au nouvel uid par
  `sync.rattacher_compte`, sans doublon.
- Opérations en attente : date lue dans le libellé (`… DU jj/mm`), identifiant sans date, donc stable d'un jour à l'autre.
- Alerte si aucune synchronisation réussie depuis 48 h (`daily_check`).
  Un compte sans `uid` dans la réponse est ignoré.
- `data/eb_private.pem` : hors git, dans le bundle secrets chiffré de `backup.sh`.
- Aucun query param métier (body JSON Pydantic), sauf le callback imposé par Enable Banking.

## Tests
```bash
docker run --rm -v "$PWD/www/budget/backend":/app -w /app docker_budget python test_budget.py
node www/budget/tests/xss.mjs
```

## Voir aussi
[Capital](../capital-control/README.md) (carte Investissements) · [auth](../../docs/auth.md) ·
[discord](../../docs/discord.md) · [design system](../_ui/README.md)
