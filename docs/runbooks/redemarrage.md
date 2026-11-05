# Redémarrer le serveur

## Avant

```bash
bash scripts/backup.sh
docker ps -a --format '{{.Names}} {{.Status}}' | sort > ~/avant-docker.txt
sudo findmnt --verify; systemctl --failed --no-legend
docker exec nginx-proxy-local nginx -t
```

Ne pas arrêter tous les conteneurs à la main : avec `unless-stopped`, ils ne repartiraient pas.

## Après

```bash
systemctl --failed --no-legend; df -h /
docker ps -a --filter status=exited --filter status=restarting --format '{{.Names}} {{.Status}}'
docker exec nginx-proxy-local nginx -t && docker exec nginx-proxy-local nginx -s reload
docker exec nginx-dashboard nginx -t && docker exec nginx-dashboard nginx -s reload
diff ~/avant-docker.txt <(docker ps -a --format '{{.Names}} {{.Status}}' | sort) | grep -v Up
```

Laisser passer le contrôle horaire et lire le rapport de sauvegarde de la nuit.
