# Sauvegardes et surveillance

Scripts dans [scripts/](../scripts/), exécutés par cron.

| Script | Rythme | Rôle |
|---|---|---|
| [backup.sh](../scripts/backup.sh) | Chaque nuit | Dumps SQLite cohérents (`.backup`, compatible WAL), archive des configurations, secrets chiffrés, miroir sur un second disque |
| [heartbeat.sh](../scripts/heartbeat.sh) | Chaque heure | Disques, conteneurs, sondes HTTP, VPN, fraîcheur des sauvegardes, RAM, charge, certificat, dead-man switch |
| [daily-report.sh](../scripts/daily-report.sh) | Chaque matin | Récapitulatif Discord des dernières 24 h |
| [notify-discord.sh](../scripts/notify-discord.sh) | À la demande | Envoi des alertes, avec mention au niveau critique |
| [cert-renew-hook.sh](../scripts/cert-renew-hook.sh) | Au renouvellement | Copie le certificat, recharge nginx, vérifie que le certificat servi est bien le nouveau |

## Principes

- **Chiffrement asymétrique avec `age` :** le serveur ne détient que la clé publique. La clé privée, indispensable
  pour restaurer, reste hors du serveur.
- **Aucun fichier sensible en clair sur le second disque :** seules les versions `.age` y sont copiées. Sans clé
  publique disponible, le miroir est sauté plutôt que de copier en clair.
- **Rotation :** 7 archives de configuration et 7 archives de secrets.
- **Surveillance sans liste à tenir :** tout conteneur à redémarrage automatique est surveillé d'office.
- **Pas de spam :** chaque alerte n'est envoyée qu'une fois, puis un message signale le retour à la normale.
- **Dead-man switch :** un ping horaire vers healthchecks.io ; s'il cesse, le service externe alerte, même si le serveur est totalement arrêté.

Restauration : [runbooks/restauration.md](runbooks/restauration.md).
