"""
ATLAS Phase 1 -- core backend + verification API (no blockchain yet).

Run locally:
    docker compose up -d          # starts Postgres
    uvicorn app.main:app --reload

Then open http://localhost:8000/docs for interactive API docs.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import Base, engine
from app.routers import credentials, students, verification

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 1 prototype: create tables directly from the models.
    # Swap for Alembic migrations before this touches real student data.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Phase 1 of the ATLAS build plan: student identity records, "
        "credential issuance, proof-hash generation, and a local "
        "verified/invalid/revoked check -- all without touching a "
        "blockchain. Phase 2 replaces the local proof lookup in "
        "/verify with a smart-contract read; nothing else in this "
        "API's shape needs to change."
    ),
    lifespan=lifespan,
)


app.include_router(students.router)
app.include_router(credentials.router)
app.include_router(verification.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "phase": "1", "blockchain": "not yet integrated"}
