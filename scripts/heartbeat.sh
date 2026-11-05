#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
# HomeLab — Heartbeat & surveillance locale (cron horaire)
#   1. Vérifie l'espace disque (/ et DATA) → alerte Discord si élevé
#   2. Vérifie les conteneurs critiques → alerte Discord si l'un est down
#   3. Ping healthchecks.io (dead-man switch) → si ce ping s'arrête,
#      healthchecks alerte TON Discord (= serveur totalement HS)
#
#   L'UUID healthchecks se met dans scripts/.healthchecks_uuid (1 ligne).
#   Tant qu'il est absent, le heartbeat local marche quand même.
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

DIR="/srv/homelab/scripts"
NOTIFY="$DIR/notify-discord.sh"
STATE="$DIR/.heartbeat_state"          # évite le spam : ne réalerte pas en boucle
HC_FILE="$DIR/.healthchecks_uuid"

DISK_WARN=85     # % occupation racine
DATA_WARN=85       # % occupation DATA (données + miroir des sauvegardes)
DATA_PATH="/mnt/data"
RAM_WARN=92      # % RAM
SWAP_WARN=92     # % swap
LOAD_WARN=8     # load1
CERT_WARN=10     # jours avant expiration du wildcard
DB="/srv/homelab/www/dashboard/data/metrics.db"
CERT="/srv/homelab/docker/nginx-proxy/certs/homelab.crt"

touch "$STATE"
already() { grep -qxF "$1" "$STATE"; }
mark()    { echo "$1" >> "$STATE"; }
# grep renvoie 1 quand plus aucune ligne ne subsiste : sans le "|| true" le mv
# derrière && ne s'exécutait pas et la marque restait à vie, ce qui bloquait
# toute nouvelle alerte pour ce motif (already "..." restait vrai).
clear_mark() { grep -vxF "$1" "$STATE" > "$STATE.tmp" 2>/dev/null || true; mv -f "$STATE.tmp" "$STATE" 2>/dev/null || true; }

# ── 1. Disque racine ──
USE=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [ "${USE:-0}" -ge "$DISK_WARN" ]; then
    if ! already "disk_root"; then
        "$NOTIFY" warn "Disque racine à ${USE}% (seuil ${DISK_WARN}%). Nettoyage conseillé." && mark "disk_root"
    fi
else
    clear_mark "disk_root"
fi

# ── 1b. Disque DATA (données + miroir des sauvegardes) ──
# Testé comme point de montage AVANT df : si le DATA se démonte, df tomberait sur la
# racine et renverrait un pourcentage rassurant mais faux.
if mountpoint -q "$DATA_PATH"; then
    clear_mark "data_unmounted"
    DATA_USE=$(df --output=pcent "$DATA_PATH" | tail -1 | tr -dc '0-9')
    if [ "${DATA_USE:-0}" -ge "$DATA_WARN" ]; then
        if ! already "disk_data"; then
            DATA_FREE=$(df -h --output=avail "$DATA_PATH" | tail -1 | tr -d ' ')
            "$NOTIFY" warn "Disque DATA à ${DATA_USE}% (seuil ${DATA_WARN}%) — ${DATA_FREE} libres." && mark "disk_data"
        fi
    else
        clear_mark "disk_data"
    fi
else
    if ! already "data_unmounted"; then
        "$NOTIFY" crit "Disque DATA **NON MONTÉ** — miroir des sauvegardes inopérant." && mark "data_unmounted"
    fi
fi

# ── 2. Conteneurs : tout conteneur à redémarrage automatique doit tourner, et être sain ──
# Pas de liste : un service ajouté est surveillé d'office. Message de retour à la normale.
ETATS=$(docker ps -aq 2>/dev/null | xargs -r docker inspect -f '{{.Name}}|{{.HostConfig.RestartPolicy.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null)
if [ -z "$ETATS" ]; then
    already "docker_ko" || { "$NOTIFY" crit "Docker ne répond pas : état des conteneurs inconnu." && mark "docker_ko"; }
else
    clear_mark "docker_ko"
    while IFS='|' read -r NOM POLICE ETAT SANTE; do
        NOM=${NOM#/}
        [ "$POLICE" = "no" ] && continue
        if [ "$ETAT" != "running" ] || [ "$SANTE" = "unhealthy" ]; then
            already "down_$NOM" || { "$NOTIFY" crit "Conteneur **$NOM** : ${ETAT}${SANTE:+, $SANTE}." && mark "down_$NOM"; }
        elif already "down_$NOM"; then
            "$NOTIFY" ok "Conteneur **$NOM** de nouveau en service." && clear_mark "down_$NOM"
        fi
    done <<< "$ETATS"
fi

# ── 2b. Service réel : tunnel public et proxy Tailscale répondent (3 essais avant d'alerter) ──
sonde(){  # $1=motif $2=libellé $3...=arguments curl (URL comprise)
    local motif="$1" libelle="$2" code i; shift 2
    for i in 1 2 3; do
        code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$@" 2>/dev/null)
        case "$code" in 2??|3??) break ;; esac
        sleep 5
    done
    case "$code" in
        2??|3??)
            if already "$motif"; then "$NOTIFY" ok "$libelle de nouveau joignable." && clear_mark "$motif"; fi ;;
        *)  already "$motif" || { "$NOTIFY" crit "$libelle ne répond pas (HTTP ${code:-000})." && mark "$motif"; } ;;
    esac
}
sonde sonde_tunnel "Site public (tunnel Cloudflare)" https://example.com/login.html
sonde sonde_proxy "Proxy Tailscale (nginx-proxy-local)" --resolve budget.example.com:443:127.0.0.1 https://budget.example.com/api/budget/health

# ── 2c. Tailscale ──
TS=$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("BackendState"), d.get("Self",{}).get("Online"))' 2>/dev/null)
if [ "$TS" = "Running True" ]; then
    if already "tailscale"; then "$NOTIFY" ok "Tailscale de nouveau en ligne." && clear_mark "tailscale"; fi
else
    already "tailscale" || { "$NOTIFY" crit "Tailscale hors ligne (${TS:-inconnu})." && mark "tailscale"; }
fi

# ── 2d. Sauvegarde du jour : l'archive la plus récente a moins de 26 h ──
DERNIERE=$(ls -1t /srv/homelab/backups/config/config_*.tar.gz 2>/dev/null | head -1)
if [ -n "$DERNIERE" ] && [ $(( $(date +%s) - $(stat -c %Y "$DERNIERE") )) -lt 93600 ]; then
    clear_mark "backup_vieux"
else
    already "backup_vieux" || { "$NOTIFY" crit "Aucune sauvegarde depuis plus de 26 h." && mark "backup_vieux"; }
fi

# ── 3. RAM / Swap / Load (réutilise la dernière snapshot du monitoring) ──
if [ -f "$DB" ]; then
    IFS='|' read -r RAM SWAP LOAD <<< "$(sqlite3 "$DB" "SELECT CAST(memory AS INT),CAST(swap AS INT),load1 FROM snapshots ORDER BY ts DESC LIMIT 1;" 2>/dev/null)"
    if [ "${RAM:-0}" -ge "$RAM_WARN" ]; then
        already "ram"  || { "$NOTIFY" warn "RAM à ${RAM}% (seuil ${RAM_WARN}%)." && mark "ram"; }
    else clear_mark "ram"; fi
    if [ "${SWAP:-0}" -ge "$SWAP_WARN" ]; then
        already "swap" || { "$NOTIFY" warn "Swap à ${SWAP}% (seuil ${SWAP_WARN}%)." && mark "swap"; }
    else clear_mark "swap"; fi
    LOAD_INT=${LOAD%%.*}
    if [ "${LOAD_INT:-0}" -ge "$LOAD_WARN" ]; then
        already "load" || { "$NOTIFY" warn "Charge système élevée (load1=${LOAD})." && mark "load"; }
    else clear_mark "load"; fi
fi

# ── 4. Expiration du certificat wildcard ──
if [ -r "$CERT" ]; then
    END=$(openssl x509 -enddate -noout -in "$CERT" 2>/dev/null | cut -d= -f2)
    if [ -n "$END" ]; then
        DAYS=$(( ( $(date -d "$END" +%s) - $(date +%s) ) / 86400 ))
        if [ "$DAYS" -lt "$CERT_WARN" ]; then
            already "cert" || { "$NOTIFY" crit "Cert wildcard expire dans ${DAYS}j — renouvellement à vérifier." && mark "cert"; }
        else clear_mark "cert"; fi
    fi
fi

# ── 5. Dead-man switch healthchecks.io ──
if [ -s "$HC_FILE" ]; then
    UUID=$(head -1 "$HC_FILE" | tr -d '[:space:]')
    [ -n "$UUID" ] && curl -fsS -m 10 --retry 3 "https://hc-ping.com/$UUID" >/dev/null 2>&1 || true
fi

exit 0
