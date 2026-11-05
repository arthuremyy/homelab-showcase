#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
# HomeLab — Rapport quotidien Discord (canal #news, cron 6h)
#   Réutilise les métriques DÉJÀ collectées (snapshots dans metrics.db)
#   + état conteneurs / disques / backups / cert. Un seul embed récap.
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail

BASE="/srv/homelab"
ENV_FILE="$BASE/docker/.env"
DB="$BASE/www/dashboard/data/metrics.db"
CERT="$BASE/docker/nginx-proxy/certs/homelab.crt"
WEBHOOK=$(grep -E '^DISCORD_WEBHOOK_HEALTH=' "$ENV_FILE" | cut -d= -f2-)
[ -z "$WEBHOOK" ] && { echo "webhook absent"; exit 1; }

q(){ sqlite3 "$DB" "$1" 2>/dev/null; }
now=$(date +%s)

# ── Métriques 24h (réutilise snapshots) ──
IFS='|' read -r CPU_AVG CPU_MAX RAM_AVG RAM_MAX SWAP_MAX LOAD_MAX <<EOF
$(q "SELECT ROUND(AVG(cpu),1),ROUND(MAX(cpu),1),ROUND(AVG(memory),1),ROUND(MAX(memory),1),ROUND(MAX(swap),1),ROUND(MAX(load1),2) FROM snapshots WHERE ts>strftime('%s','now')-86400;")
EOF
IFS='|' read -r RAM_NOW SWAP_NOW CONT_NOW <<EOF
$(q "SELECT memory,swap,containers FROM snapshots ORDER BY ts DESC LIMIT 1;")
EOF

# ── Conteneurs ──
UP=$(docker ps -q | wc -l); TOTAL=$(docker ps -aq | wc -l)
DOWN=$(docker ps -a --filter 'status=exited' --filter 'status=dead' --format '{{.Names}}' | paste -sd', ' -)

# ── Disques ──
ROOT=$(df -h / | awk 'NR==2{print $5" utilisé, "$4" libre"}')
if mountpoint -q /mnt/data; then
    DATA=$(df -h /mnt/data | awk 'NR==2{print $5" utilisé, "$4" libre"}')
else
    DATA="⚠️ NON MONTÉ"
fi

# ── Fraîcheur backups ──
age_h(){ local f; f=$(ls -t $1 2>/dev/null | head -1); [ -n "$f" ] && echo "$((( now - $(stat -c %Y "$f") ) / 3600 ))h" || echo "?"; }
CFG_AGE=$(age_h "$BASE/backups/config/config_*.tar.gz")
SEC_OK=$(ls "$BASE/backups/secrets/"secrets_*.tar.gz.age >/dev/null 2>&1 && echo "✅" || echo "⚠️ absent")

# ── Cert wildcard ──
CERT_DAYS="?"
if [ -r "$CERT" ]; then
    END=$(openssl x509 -enddate -noout -in "$CERT" 2>/dev/null | cut -d= -f2)
    [ -n "$END" ] && CERT_DAYS=$(( ( $(date -d "$END" +%s) - now ) / 86400 ))
fi

UP_TIME=$(awk '{printf "%dj %dh", $1/86400, ($1%86400)/3600}' /proc/uptime)

# ── Statut global (couleur embed) ──
STATUS="🟢 Tout est nominal"; COLOR=3066993   # vert
WARN=""
[ "$UP" -lt "$TOTAL" ]                    && { STATUS="🟠 Attention"; COLOR=15105570; WARN+="• Conteneur(s) arrêté(s): ${DOWN:-?}\n"; }
[ "${CERT_DAYS}" != "?" ] && [ "${CERT_DAYS}" -lt 10 ] && { STATUS="🟠 Attention"; COLOR=15105570; WARN+="• Cert expire dans ${CERT_DAYS}j\n"; }
[ "$DATA" = "⚠️ NON MONTÉ" ]                && { STATUS="🔴 Problème"; COLOR=15158332; WARN+="• DATA démonté → plus de backup hors-disque\n"; }
ROOT_PCT=$(df / | awk 'NR==2{print $5}' | tr -dc '0-9')
[ "${ROOT_PCT:-0}" -ge 85 ]              && { STATUS="🟠 Attention"; COLOR=15105570; WARN+="• Disque racine à ${ROOT_PCT}%\n"; }

export WEBHOOK STATUS COLOR WARN CPU_AVG CPU_MAX RAM_AVG RAM_MAX RAM_NOW SWAP_MAX SWAP_NOW LOAD_MAX \
       UP TOTAL DOWN ROOT DATA CFG_AGE SEC_OK CERT_DAYS UP_TIME

python3 <<'PY'
import os, json, urllib.request

def g(k, d=""): return os.environ.get(k, d) or d

warn = g("WARN").strip()
fields = [
    {"name":"🖥️ Système (24h)",
     "value":f"CPU moy {g('CPU_AVG','?')}% / max {g('CPU_MAX','?')}%\n"
             f"RAM moy {g('RAM_AVG','?')}% / max {g('RAM_MAX','?')}% (now {g('RAM_NOW','?')}%)\n"
             f"Swap max {g('SWAP_MAX','?')}% · Load max {g('LOAD_MAX','?')}",
     "inline":True},
    {"name":"📦 Conteneurs",
     "value":f"{g('UP')}/{g('TOTAL')} actifs" + (f"\n⚠️ down: {g('DOWN')}" if g('DOWN') else " ✅"),
     "inline":True},
    {"name":"💾 Disques",
     "value":f"Racine: {g('ROOT')}\nDATA: {g('DATA')}","inline":False},
    {"name":"🗄️ Backups",
     "value":f"Configs: il y a {g('CFG_AGE')}\nSecrets chiffrés: {g('SEC_OK')}",
     "inline":True},
    {"name":"🔐 Divers",
     "value":f"Cert wildcard: {g('CERT_DAYS')}j restants\nUptime: {g('UP_TIME')}","inline":True},
]
if warn:
    fields.insert(0, {"name":"⚠️ À regarder","value":warn,"inline":False})

embed = {
    "title": f"Rapport quotidien — {g('STATUS')}",
    "color": int(g("COLOR","3066993")),
    "fields": fields,
    "footer": {"text":"HomeLab"},
}
data = json.dumps({"username":"HomeLab Infra","embeds":[embed]}).encode()
req = urllib.request.Request(g("WEBHOOK"), data=data,
    headers={"Content-Type":"application/json", "User-Agent":"HomeLab-Infra/1.0"})
try:
    urllib.request.urlopen(req, timeout=10); print("✓ rapport envoyé")
except Exception as e:
    print("✗ échec:", e); raise SystemExit(1)
PY
