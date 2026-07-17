import logging
import sys
from pathlib import Path

from app.core.config import settings

# ---------------------------------------------------------------------------
# Log file setup
# ---------------------------------------------------------------------------
# Resolve the logs/ directory relative to this file's grandparent (project root).
# Using Path ensures this works regardless of where uvicorn is launched from.
# ---------------------------------------------------------------------------

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"


def setup_logging() -> None:
    """
    Configure application-wide logging.

    - Console handler : coloured output for development readability.
    - File handler    : persistent log file at logs/app.log.

    Call this function once at application startup (in main.py lifespan).
    After that, every module uses:  logger = logging.getLogger(__name__)
    """

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Shared formatter — consistent format across both handlers
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # -- Console handler --
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # -- File handler --
    # mode="a" appends to the file across restarts (does not wipe on reload).
    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    # -- Root logger --
    # Setting the root logger propagates the config to every child logger
    # (i.e. every module that calls logging.getLogger(__name__)).
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid adding duplicate handlers if setup_logging() is called more than once
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers we don't need in our log stream
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
