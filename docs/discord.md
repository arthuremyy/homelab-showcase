# Discord : un salon par domaine

| Salon | Variable (`docker/.env`) | Qui poste |
|---|---|---|
| #news-health | `DISCORD_WEBHOOK_HEALTH` | [notify-discord.sh](../scripts/notify-discord.sh) (← `heartbeat.sh`, `backup.sh`), `daily-report.sh` |
| #news-job | `DISCORD_WEBHOOK_JOBS` | Job Radar (repli si le profil n'a pas de webhook) |
| #new-financing | `DISCORD_WEBHOOK_FINANCE` | Capital (briefing, récapitulatif, alertes), Budget (accès bancaire, synchro, solde bas) |

- `DISCORD_MENTION_USER_ID` : `@mention` ajoutée par `notify-discord.sh` au niveau `crit`.
- Le salon d'un webhook se vérifie par `GET` sur son URL (champ `channel_id`).
- Ne jamais journaliser une URL de webhook : toute application qui poste sur Discord passe le logger
  `httpx` en WARNING (Budget, Capital).
