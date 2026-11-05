import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    db_path: str = os.getenv("DB_PATH", "/data/jobs.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    discord_webhook: str = os.getenv("DISCORD_WEBHOOK_JOBS", "")
    # France Travail (lot 2) — inactif tant que les clés sont absentes
    ft_client_id: str = os.getenv("FT_CLIENT_ID", "")
    ft_client_secret: str = os.getenv("FT_CLIENT_SECRET", "")
    # Adzuna (lot 2)
    adzuna_app_id: str = os.getenv("ADZUNA_APP_ID", "")
    adzuna_app_key: str = os.getenv("ADZUNA_APP_KEY", "")
    # Jooble — clé partenaire, 500 requêtes au total (cf. sources/jooble.py)
    jooble_api_key: str = os.getenv("JOOBLE_API_KEY", "")
    collect_hours: int = int(os.getenv("JOBS_COLLECT_HOURS", "2"))
    tz: str = os.getenv("TZ", "Europe/Paris")


settings = Settings()
