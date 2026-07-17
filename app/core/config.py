from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.

    Pydantic validates every field at startup. If a required value is
    missing or has the wrong type, the app will refuse to start with a
    clear validation error — catching misconfiguration early.
    """

    # -- Application --
    APP_NAME: str = "AI Test Automation Platform"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # -- Database --
    DATABASE_URL: str

    # -- File storage --
    # Directory where uploaded PDFs are saved (relative to project root)
    UPLOAD_DIR: str = "uploads"

    # -- Gemini LLM --
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "models/gemini-2.0-flash"   # use full model ID for google.genai SDK

    # -- Logging --
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",          # Load values from .env file
        env_file_encoding="utf-8",
        case_sensitive=True,      # DATABASE_URL ≠ database_url
        extra="ignore",           # Silently ignore unknown .env keys
    )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
# Import this instance everywhere:  from app.core.config import settings
# Pydantic reads and validates .env exactly once when this module loads.
# ---------------------------------------------------------------------------

settings = Settings()
