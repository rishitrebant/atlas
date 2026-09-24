"""
Application configuration.

Settings are loaded from environment variables (see .env.example).
Nothing sensitive is hard-coded here.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres connection. Defaults match docker-compose.yml for local dev.
    database_url: str = (
        "postgresql+psycopg2://atlas:atlas@localhost:5432/atlas"
    )

    # Simple shared-secret auth for admin/issuer endpoints (student records,
    # credential issuance, revocation). Phase 1 keeps auth simple on purpose;
    # swap for OAuth2/JWT + role-based access before any real deployment.
    admin_api_key: str = "change-me-in-.env"

    # App metadata
    app_name: str = "ATLAS Identity & Verification API"
    app_version: str = "0.1.0-phase1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
