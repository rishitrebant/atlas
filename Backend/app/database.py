"""
SQLAlchemy engine, session factory, and declarative base.

This is the ONE private database referenced throughout the ATLAS research
brief: student profiles and credential records live here. In Phase 2, only
a proof hash derived from a credential (see app/security.py) ever leaves
this database and goes on-chain -- never the raw fields below.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
