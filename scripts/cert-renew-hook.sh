#!/bin/bash
# Post-renewal hook : copier les nouveaux certs et recharger nginx
set -e

CERT_DIR="/etc/letsencrypt/live/example.com"
NGINX_DIR="/srv/homelab/docker/nginx-proxy/certs"

cp "$CERT_DIR/fullchain.pem" "$NGINX_DIR/homelab.crt"
cp "$CERT_DIR/privkey.pem"   "$NGINX_DIR/homelab.key"
chmod 644 "$NGINX_DIR/homelab.crt"
chmod 600 "$NGINX_DIR/homelab.key"

# Un échec doit se voir : certificat copié mais non servi, sinon, jusqu'à l'expiration.
if ! docker exec nginx-proxy-local nginx -t >/dev/null 2>&1 \
    || ! docker exec nginx-proxy-local nginx -s reload >/dev/null 2>&1; then
    /srv/homelab/scripts/notify-discord.sh crit "Certificat renouvelé mais nginx-proxy-local non rechargé." || true
    echo "[$(date '+%F %T')] Cert copié, ÉCHEC du rechargement de nginx" >&2
    exit 1
fi

# Le certificat servi doit être celui du fichier
SERVI=$(echo | timeout 5 openssl s_client -connect 127.0.0.1:443 -servername budget.example.com 2>/dev/null | openssl x509 -noout -fingerprint -sha256)
FICHIER=$(openssl x509 -in "$NGINX_DIR/homelab.crt" -noout -fingerprint -sha256)
if [ "$SERVI" != "$FICHIER" ]; then
    /srv/homelab/scripts/notify-discord.sh crit "Certificat renouvelé mais pas celui servi par nginx-proxy-local." || true
    echo "[$(date '+%F %T')] Cert servi différent du fichier" >&2
    exit 1
fi

echo "[$(date '+%F %T')] Cert renouvelé, nginx rechargé, certificat servi vérifié"
