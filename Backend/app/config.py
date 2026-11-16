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

    # Separate shared secret for the ESP32 gate device. Kept distinct from
    # the admin key on purpose: the device should only be able to perform
    # gate scans, never create students, issue credentials, or read the
    # audit log.
    device_api_key: str = "change-me-device-key-in-.env"

    # App metadata
    app_name: str = "ATLAS Identity & Verification API"
    app_version: str = "0.2.0-phase2"

    # ---------------- Phase 2: blockchain ----------------
    # Points at a local Hardhat devnet by default (`npx hardhat node` in
    # blockchain/). Swap for a public testnet RPC URL later if you ever
    # move off a local chain -- nothing else in the backend needs to change.
    web3_rpc_url: str = "http://127.0.0.1:8545"

    # Hardhat's well-known account #0. This is a PUBLICLY DOCUMENTED test
    # key that ships with Hardhat itself -- every Hardhat install has the
    # exact same one, it holds no real funds, and anyone can look it up.
    # It is safe to commit here for local development ONLY. If this project
    # ever points at a real network, replace this with your own key via
    # .env and never commit that value.
    web3_private_key: str = (
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
    )

    # Filled in after you run `node deploy.js` in blockchain/ -- it prints
    # the deployed address, paste it here (or into .env).
    contract_address: str = ""

    # When false, chain writes are skipped entirely (logged as a warning)
    # instead of raising. Lets the rest of the API keep working if the
    # local Hardhat node isn't running yet while you're still setting up.
    chain_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
