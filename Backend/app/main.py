"""
ATLAS Phase 2 -- identity + credential API, RFID gate bridge, blockchain logging.

Run locally (three terminals):
    1. cd blockchain && npx hardhat node          # local chain
    2. cd Backend && docker compose up -d         # Postgres
       uvicorn app.main:app --reload --host 0.0.0.0
    3. open http://localhost:8000/                # frontend

--host 0.0.0.0 matters: it lets the ESP32 on your WiFi reach the API.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import get_settings
from app.database import Base, engine
from app.routers import credentials, gate, students, verification

settings = get_settings()


def _upgrade_existing_schema() -> None:
    """
    Base.metadata.create_all() creates missing TABLES but never adds new
    COLUMNS to tables that already exist. Phase 2 added two columns to
    `students`; this adds them to an existing Phase 1 database without
    wiping it. Idempotent -- safe to run on every startup. Postgres only
    (that's what docker-compose provides); skipped for other dialects.
    """
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE students ADD COLUMN IF NOT EXISTS rfid_uid VARCHAR(32)"))
        conn.execute(
            text("ALTER TABLE students ADD COLUMN IF NOT EXISTS inside BOOLEAN NOT NULL DEFAULT FALSE")
        )
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_students_rfid_uid ON students (rfid_uid)")
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Prototype: create tables directly from the models, then patch columns
    # added since Phase 1. Swap for Alembic migrations before real student data.
    Base.metadata.create_all(bind=engine)
    _upgrade_existing_schema()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Phase 2 of the ATLAS build plan: student identity records, "
        "credential issuance with on-chain proof hashes, an RFID gate "
        "endpoint for the ESP32, and public verification that reads the "
        "AtlasRegistry smart contract directly."
    ),
    lifespan=lifespan,
)

app.include_router(students.router)
app.include_router(credentials.router)
app.include_router(verification.router)
app.include_router(gate.router)


@app.get("/health", tags=["meta"])
def health():
    from app.chain import client as chain

    chain_ok = False
    try:
        chain_ok = chain._get_w3().is_connected()
    except Exception:  # noqa: BLE001
        chain_ok = False

    return {
        "status": "ok",
        "phase": "2",
        "blockchain": "connected" if chain_ok else "not reachable",
        "contract_configured": bool(settings.contract_address),
    }


# Serve the lightweight frontend from the same FastAPI origin (no CORS needed).
# Mounted LAST so it never shadows the API routes above.
frontend_dir = Path(__file__).resolve().parents[2] / "Frontend"
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
