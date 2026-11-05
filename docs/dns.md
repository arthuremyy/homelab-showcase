# DNS interne

AdGuard Home sert de DNS sur le VPN : blocage publicitaire et résolution des sous-domaines privés vers l'adresse
VPN du serveur. Ces noms n'existent donc pas dans le DNS public.

- Identifiants dans la variable `ADGUARD_AUTH`, jamais dans la doc.
- Le port 3000 n'est pas publié sur l'hôte : l'API se joint par l'adresse du conteneur.

```bash
AG=$(docker inspect adguard --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
AUTH=$(grep -E '^ADGUARD_AUTH=' docker/.env | cut -d= -f2-)
# Lister
curl -s -u "$AUTH" "http://$AG:3000/control/rewrite/list" | python3 -m json.tool
# Ajouter un sous-domaine privé
curl -s -u "$AUTH" -X POST "http://$AG:3000/control/rewrite/add" -H "Content-Type: application/json" \
  -d '{"domain":"monservice.example.com","answer":"100.64.0.1"}'
```

La liste de référence est celle de l'API ; `backup.sh` l'exporte chaque nuit.
