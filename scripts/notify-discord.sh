#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
# HomeLab — Notification Discord centralisée (infra homelab)
#   Usage : notify-discord.sh <niveau> "<message>"
#     niveau = info | ok | warn | crit
#     crit → ajoute une @mention (déclenche la notif push téléphone)
#
#   Poste dans #news-health (DISCORD_WEBHOOK_HEALTH) — santé du serveur.
#   Lit les variables depuis docker/.env
#   (aucun secret hardcodé ici).
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

ENV_FILE="/srv/homelab/docker/.env"
LEVEL="${1:-info}"
MESSAGE="${2:-(message vide)}"

# Récupère les variables sans sourcer tout le .env (évite les surprises)
WEBHOOK=$(grep -E '^DISCORD_WEBHOOK_HEALTH=' "$ENV_FILE" | cut -d= -f2-)
USER_ID=$(grep -E '^DISCORD_MENTION_USER_ID=' "$ENV_FILE" | cut -d= -f2-)

[ -z "$WEBHOOK" ] && { echo "notify-discord: DISCORD_WEBHOOK_HEALTH introuvable" >&2; exit 1; }

case "$LEVEL" in
    ok)   EMOJI="✅"; PREFIX="" ;;
    warn) EMOJI="⚠️"; PREFIX="" ;;
    crit) EMOJI="🚨"; PREFIX="<@${USER_ID}> " ;;   # mention = push tel
    *)    EMOJI="ℹ️"; PREFIX="" ;;
esac

HOST=$(hostname)
CONTENT="${PREFIX}${EMOJI} **[${HOST}]** ${MESSAGE}"

# jq-free : échappe les guillemets et retours ligne pour le JSON
ESCAPED=$(printf '%s' "$CONTENT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

curl -fsS -m 10 -H "Content-Type: application/json" \
    -d "{\"content\": ${ESCAPED}, \"username\": \"HomeLab Infra\"}" \
    "$WEBHOOK" >/dev/null 2>&1 \
    && exit 0 \
    || { echo "notify-discord: échec du POST Discord" >&2; exit 1; }
