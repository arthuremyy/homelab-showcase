import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    db_path: str = os.getenv("DB_PATH", "/data/budget.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    discord_webhook: str = os.getenv("DISCORD_WEBHOOK_FINANCE", "")
    # Enable Banking (mode « restricted » : uniquement les comptes reliés dans leur console)
    eb_app_id: str = os.getenv("EB_APP_ID", "")
    eb_key_path: str = os.getenv("EB_KEY_PATH", "/data/eb_private.pem")
    eb_aspsp: str = os.getenv("EB_ASPSP", "Ma Banque")
    eb_country: str = os.getenv("EB_COUNTRY", "FR")
    eb_redirect_url: str = os.getenv("EB_REDIRECT_URL",
                                     "https://budget.example.com/api/budget/bank/callback")
    # Capital (investissements) — lu en interne, réseau Docker
    capital_url: str = os.getenv("CAPITAL_URL", "http://capital-control:8100")
    tz: str = os.getenv("TZ", "Europe/Paris")


settings = Settings()
