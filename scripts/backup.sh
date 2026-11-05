#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
# HomeLab — Backup configs + données critiques + secrets chiffrés
#   - Dumps SQLite cohérents (.backup) : capital.db, metrics.db
#   - Archive des configs (compose, nginx, cloudflared, scripts, docs)
#   - Export des rewrites AdGuard
#   - Bundle SECRETS chiffré avec age (clé publique dans .age-recipient.pub)
#   - Miroir de TOUT backups/ vers le DATA (2e disque physique)
#   - Alerte Discord (ok/crit) + ping healthchecks
#   Rotation : 7 archives config + 7 bundles secrets
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

BASE="/srv/homelab"
BACKUP_DIR="$BASE/backups"
CONFIG_DIR="$BACKUP_DIR/config"
SECRETS_DIR="$BACKUP_DIR/secrets"
DATA="/mnt/data/backups"
NOTIFY="$BASE/scripts/notify-discord.sh"
HC_FILE="$BASE/scripts/.healthchecks_uuid"
AGE_PUB="$BASE/scripts/.age-recipient.pub"
LOG="$BACKUP_DIR/.config-backup.log"
DATE=$(date +%Y%m%d_%H%M%S)

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
ERRORS=0

mkdir -p "$CONFIG_DIR" "$SECRETS_DIR"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

log "─── Début backup config ${DATE} ───"

# ── 1. Dumps SQLite cohérents ──
mkdir -p "$STAGE/db"
dump_db(){  # $1=source  $2=nom
    [ -f "$1" ] || return 0
    if sqlite3 "$1" ".backup '$STAGE/db/$2'" 2>>"$LOG"; then
        log "  ✓ dump $2"
    else
        log "  ✗ dump $2 (verrou ou accès ?)"; ERRORS=$((ERRORS+1))
    fi
}
dump_db "$BASE/www/capital-control/data/capital.db" capital.db
dump_db "$BASE/www/dashboard/data/metrics.db"       metrics.db
dump_db "$BASE/www/job-radar/data/jobs.db"          jobs.db
dump_db "$BASE/www/budget/data/budget.db"           budget.db

# ── 2. Export des rewrites AdGuard (best-effort ; creds depuis .env) ──
ADGUARD_AUTH=$(grep -E '^ADGUARD_AUTH=' "$BASE/docker/.env" | cut -d= -f2-)
ADGUARD_IP=$(docker inspect adguard --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)
if [ -n "${ADGUARD_IP:-}" ] && [ -n "${ADGUARD_AUTH:-}" ]; then
    curl -fsS -m 10 -u "$ADGUARD_AUTH" "http://${ADGUARD_IP}:3000/control/rewrite/list" \
        -o "$STAGE/adguard_rewrites.json" 2>>"$LOG" \
        && log "  ✓ export rewrites AdGuard" \
        || log "  ⚠ export AdGuard échoué (non bloquant)"
else
    log "  ⚠ ADGUARD_AUTH absent de .env → export AdGuard sauté"
fi

# ── 3. Archive des configs (petits fichiers, non secrets) ──
cp -a "$STAGE/db" "$STAGE/adguard_rewrites.json" "$STAGE/" 2>/dev/null
tar czf "$CONFIG_DIR/config_${DATE}.tar.gz" \
    -C "$BASE" \
        docker/docker-compose.yml \
        config \
        docker/nginx-proxy/conf.d \
        docker/cloudflared/config.yml \
        scripts \
        docs \
    -C "$STAGE" \
        db adguard_rewrites.json \
    2>>"$LOG" \
    && log "  ✓ archive config ($(du -h "$CONFIG_DIR/config_${DATE}.tar.gz" | cut -f1))" \
    || { log "  ✗ archive config"; ERRORS=$((ERRORS+1)); }

# ── 4. Bundle SECRETS chiffré (age) ──
if [ -s "$AGE_PUB" ]; then
    RECIP=$(head -1 "$AGE_PUB" | tr -d '[:space:]')
    SECRET_FILES="docker/.env www/capital-control/.env docker/cloudflared/creds.json"
    # Clé privée Enable Banking (Budget) : seulement si elle existe, un fichier absent ferait échouer tar
    [ -f "$BASE/www/budget/data/eb_private.pem" ] && SECRET_FILES="$SECRET_FILES www/budget/data/eb_private.pem"
    crontab -l > "$STAGE/crontab.homelab" 2>/dev/null
    # Réglages de l'hôte lisibles sans root
    HOST_FILES=""
    for f in etc/docker/daemon.json; do
        [ -r "/$f" ] && HOST_FILES="$HOST_FILES $f"
    done
    # shellcheck disable=SC2086
    if tar czf - -C "$BASE" $SECRET_FILES -C "$STAGE" crontab.homelab -C / $HOST_FILES 2>/dev/null \
        | age -r "$RECIP" > "$SECRETS_DIR/secrets_${DATE}.tar.gz.age" 2>>"$LOG"; then
        log "  ✓ secrets chiffrés (age → $(basename "$SECRETS_DIR"))"
    else
        log "  ✗ chiffrement secrets"; ERRORS=$((ERRORS+1))
    fi
else
    log "  ⚠ clé publique age absente ($AGE_PUB) → SECRETS NON SAUVEGARDÉS (fournir la clé)"
fi

# ── 5. Rotation (garder 7) ──
prune(){ ls -1t "$1"/$2 2>/dev/null | tail -n +8 | xargs -r rm -f; }
prune "$CONFIG_DIR"  "config_*.tar.gz"
prune "$SECRETS_DIR" "secrets_*.tar.gz.age"

# ── 5bis. Chiffrement de ce qui part sur le DATA (sans permissions Unix) ──
# Le SSD garde les archives en clair ; le DATA ne reçoit que leur version .age.
chiffrer_pour_data(){
    local f
    for f in "$@"; do
        [ -f "$f" ] || continue
        [ -s "$f.age" ] && [ ! "$f" -nt "$f.age" ] && continue
        if age -R "$AGE_PUB" -o "$f.age.tmp" "$f" 2>>"$LOG"; then
            mv "$f.age.tmp" "$f.age"
        else
            rm -f "$f.age.tmp"; log "  ✗ chiffrement $(basename "$f")"; ERRORS=$((ERRORS+1))
        fi
    done
}
chiffrer_pour_data "$CONFIG_DIR"/config_*.tar.gz
prune "$CONFIG_DIR" "config_*.tar.gz.age"

# ── 6. Miroir vers le DATA (2e disque physique), sans aucun fichier sensible en clair ──
if [ ! -s "$AGE_PUB" ]; then
    log "  ✗ clé publique age absente : miroir DATA sauté pour ne rien y copier en clair"; ERRORS=$((ERRORS+1))
elif mountpoint -q /mnt/data; then
    if rsync -rtD --delete --delete-excluded \
        --exclude='/config/config_*.tar.gz' --exclude='*.age.tmp' \
        "$BACKUP_DIR/" "$DATA/" 2>>"$LOG"; then
        log "  ✓ miroir DATA à jour ($(du -sh "$DATA" 2>/dev/null | cut -f1))"
    else
        log "  ✗ rsync DATA"; ERRORS=$((ERRORS+1))
    fi
else
    log "  ✗ DATA non monté — pas de copie hors-disque !"; ERRORS=$((ERRORS+1))
fi

# ── 7. Notification + heartbeat ──
if [ "$ERRORS" -eq 0 ]; then
    "$NOTIFY" ok "Backup quotidien OK — configs + capital.db + secrets, miroir DATA à jour." || true
    HC_SUFFIX=""
else
    "$NOTIFY" crit "Backup quotidien : ${ERRORS} erreur(s). Voir ${LOG}." || true
    HC_SUFFIX="/fail"
fi
if [ -s "$HC_FILE" ]; then
    curl -fsS -m 10 "https://hc-ping.com/$(head -1 "$HC_FILE" | tr -d '[:space:]')${HC_SUFFIX}" >/dev/null 2>&1 || true
fi

log "─── Fin backup config (${ERRORS} erreur(s)) ───"
exit 0
