import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.documents import router as documents_router
from app.api.selections import router as selections_router
from app.api.testcases import router as testcases_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.database.base import Base
from app.database.database import engine
import app.models  # noqa: F401 — registers all models with SQLAlchemy metadata

# ---------------------------------------------------------------------------
# Lifespan — startup and shutdown logic
# ---------------------------------------------------------------------------
# asynccontextmanager turns this into an ASGI lifespan handler.
# Code before `yield` runs at startup; code after runs at shutdown.
# This is the modern FastAPI pattern (replaces deprecated @app.on_event).
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # app.models is already imported at the top of this file, so all model
    # classes are registered with Base.metadata before create_all() runs.
    Base.metadata.create_all(bind=engine)
    tables = list(Base.metadata.tables.keys())
    logger.info("Database tables ready: %s", tables)
    logger.info("Debug mode: %s", settings.DEBUG)
    logger.info("Database: %s", settings.DATABASE_URL)

    # Ensure upload directory exists
    from pathlib import Path
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory ready: %s", settings.UPLOAD_DIR)

    yield  # Application is running and serving requests

    # --- Shutdown ---
    logger.info("Shutting down %s", settings.APP_NAME)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for AI-powered test automation.",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Register routers
app.include_router(documents_router)
app.include_router(selections_router)
app.include_router(testcases_router)


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


@app.get("/", tags=["Health"])
async def root() -> dict:
    """Health check — confirms the API is reachable."""
    logger.info("Root endpoint called.")
    return {
        "status": "ok",
        "message": f"{settings.APP_NAME} API is running.",
    }
