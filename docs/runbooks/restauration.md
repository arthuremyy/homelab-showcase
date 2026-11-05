# Restaurer

## Une base

```bash
tar xzf backups/config/config_XXXX.tar.gz db/<nom>.db -C /tmp/restau     # ou : age -d -i CLE config_XXXX.tar.gz.age | tar xzf - …
sqlite3 /tmp/restau/db/<nom>.db 'PRAGMA integrity_check'
```

Arrêter l'application, remplacer le fichier, relancer, vérifier.

## Le serveur, de zéro

1. Installer Ubuntu, Docker, `age`, `sqlite3`, `rsync` et le client VPN.
2. Extraire la dernière archive chiffrée et remettre le dépôt et ses secrets.
3. `cd docker && docker compose build && docker compose up -d`.
4. Restaurer les bases les plus récentes si l'archive est plus ancienne que les dumps.
5. Remettre le crontab, lancer `scripts/backup.sh` et lire le rapport.
6. Dérouler les vérifications de [redemarrage.md](redemarrage.md), puis se connecter à chaque application.
