import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    db_path: str = os.getenv("DB_PATH", "/data/capital.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    discord_webhook: str = os.getenv("DISCORD_WEBHOOK_FINANCE", "")
    briefing_hour: str = os.getenv("BRIEFING_HOUR", "07:30")   # HH:MM Europe/Paris
    briefing_day: int = int(os.getenv("BRIEFING_DAY", "0"))    # 0=lundi ... 6=dimanche
    weekly_report: str = os.getenv("WEEKLY_REPORT", "sun 19:00")
    tz: str = os.getenv("TZ", "Europe/Paris")


settings = Settings()
