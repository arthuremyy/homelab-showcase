# Secrets : où ils sont, jamais leur valeur

| Fichier | Contient |
|---|---|
| `docker/.env` | Secret JWT, hash du mot de passe, clés d'API, webhooks |
| `www/budget/data/eb_private.pem` | Clé privée de l'accès bancaire |
| `docker/cloudflared/creds.json` | Jeton du tunnel |
| `docker/nginx-proxy/certs/` | Clé du certificat wildcard |

- Tous ces fichiers sont exclus de git et chiffrés par [backup.sh](../scripts/backup.sh).
- Dans la doc et le code : **nom de variable seulement**. Les commandes lisent la valeur à l'exécution.
- `.env.example` ne contient jamais de vraie valeur, même anodine.
- Le logger `httpx` reste en WARNING dans les applications qui appellent un webhook ou une API à clé : sinon l'URL fuit dans les journaux.
