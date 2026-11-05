# Standard de documentation

But : un agent (ou un humain) qui arrive sait **quoi lire et où**, ne lit que ce qui concerne sa tâche,
et chaque fait n'existe qu'**à un seul endroit**.

## Où va quoi
| Information | Emplacement | Chargé |
|---|---|---|
| Règles de conduite, carte du dépôt, invariants du homelab | [README.md](../../README.md) (racine, court) | à chaque session |
| Tout ce qui est propre à **une** application | `www/<app>/README.md` (et [backend/README.md](../../backend/README.md) pour dashboard-api) | automatiquement dès qu'un fichier du dossier est lu |
| Fonctionnement commun (réseau, auth, nginx, DNS, sauvegardes, Discord, secrets) | [docs/](../) | à la demande, via l'index de la racine |
| Règles de construction communes | [docs/standards/](./) | à la demande |
| Procédure exceptionnelle (restauration, redémarrage) | [docs/runbooks/](../runbooks/) | à la demande |

## Règles
1. **Un fait = un seul endroit.** Ailleurs, un lien relatif. Avant d'écrire, chercher si le fait existe
   déjà (`grep -rn "<mot-clé>" README.md docs www/*/README.md backend/README.md`).
2. **Vérifié, pas recopié.** Un port, un nom de fichier, une constante, un horaire se vérifient dans le
   code, la config ou l'état réel avant d'être écrits ; citer le fichier qui fait foi.
3. **Même commit.** Un changement de code qui modifie un comportement documenté met à jour la doc
   dans le même commit. Nouvelle application : créer son `README.md` (gabarit ci-dessous) et l'ajouter
   à la carte de la racine.
4. **Jamais de secret.** Nom de variable et fichier seulement ([secrets.md](../secrets.md)) ;
   les commandes lisent la valeur à l'exécution.
5. **Pas de liste recopiée d'un système vivant** (rewrites DNS, conteneurs) : donner la commande qui
   l'affiche. Exception : tableaux de référence courts, avec la date de vérification.
6. **Liens Markdown relatifs** (cliquables dans l'IDE et sur GitHub). Chaque page finit, si utile, par
   « Voir aussi ».
7. **Le périmé sort** : ce qui n'est plus vrai est corrigé ou supprimé.
8. Langue : français ; phrases courtes ; tableaux plutôt que paragraphes ; pas d'emoji décoratif
   (⛔ ⚠ réservés aux interdits et pièges).

## Gabarit d'un `www/<app>/README.md`
```markdown
# <Nom> — <rôle en une ligne>

`https://<sous-domaine>.example.com` · conteneur `<nom>` · port interne **<port>** · **Tailscale uniquement**
(vhost [<x>.conf](../../docker/nginx-proxy/conf.d/<x>.conf)). Suit le [standard d'application](../../docs/standards/application.md).

## Source de vérité
<table qui fait foi ; ce qui est dérivé et comment le recalculer>

## Fichiers
| Fichier | Rôle |

## Règles à ne pas casser
<interdits, pièges constatés, avec la date et la raison>

## Tâches de fond
| Tâche | Rythme | Rôle |

## Tests
<commandes exactes>

## Voir aussi
```
