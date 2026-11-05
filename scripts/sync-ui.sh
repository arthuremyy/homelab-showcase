#!/usr/bin/env bash
# Copie le design system commun (www/_ui/) dans chaque application.
# Source unique : www/_ui/. Les copies dans */assets/ui/ ne s'éditent jamais à la main.
#
# Après exécution :
#   - tableau de bord : effet immédiat (volume monté)
#   - Job Radar, Budget : rebuild de l'image (frontend copié au build)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/www/_ui"
TARGETS=(
    "$ROOT/www/dashboard/assets/ui"
    "$ROOT/www/job-radar/frontend/assets/ui"
    "$ROOT/www/budget/frontend/assets/ui"
)

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
{
    echo "/* Généré par scripts/sync-ui.sh depuis www/_ui/ — ne pas éditer. */"
    for f in tokens base components shell; do
        echo; echo "/* ── $f.css ── */"; cat "$SRC/$f.css"
    done
} > "$tmp"

for dst in "${TARGETS[@]}"; do
    mkdir -p "$dst"
    install -m 644 "$tmp" "$dst/ui.css"
    install -m 644 "$SRC/services.js" "$SRC/shell.js" "$SRC/probe.svg" "$dst/"
    echo "ui → ${dst#$ROOT/}"
done
