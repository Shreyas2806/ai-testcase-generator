from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# ---------------------------------------------------------------------------
# Database engine
# ---------------------------------------------------------------------------
# connect_args={"check_same_thread": False} is required for SQLite only.
# SQLite's default behavior restricts a connection to the thread that created
# it. FastAPI may handle a request across multiple threads, so we disable
# this restriction. This flag is NOT needed (or valid) for PostgreSQL/MySQL.
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
# autocommit=False — we manage transactions explicitly (best practice).
# autoflush=False  — prevents implicit flushes before queries, giving us
#                    full control over when data is written to the DB.
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def get_db():
    """
    FastAPI dependency that provides a database session per request.

    Yields a session and guarantees it is closed after the request
    completes — even if an exception occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
