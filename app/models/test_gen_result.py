from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class TestGenResult(Base):
    """
    Stores one complete AI-generated test suite for a Selection.

    Each row represents a single generation run:
        - Tied to a Selection via selection_id
        - Stores the raw validated JSON returned by Gemini
        - Records which model and version was used
        - Immutable — re-generations create new rows, preserving history

    Relationships:
        selection : the Selection that was used as input context
    """

    __tablename__ = "test_gen_results"

    # -- Primary Key --
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # -- Foreign Keys --
    selection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("selections.id", ondelete="CASCADE"),
        nullable=False,
    )

    # -- Generated content --
    # The full JSON string as returned by Gemini (after validation)
    generated_json: Mapped[str] = mapped_column(Text, nullable=False)

    # The model identifier used (e.g. "gemini-1.5-flash")
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # How many retries were needed before getting valid JSON (0 = first attempt)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Dictionary mapping node_id (as str) -> content_hash at the time of generation
    # e.g., {"1": "abc...", "2": "def..."}
    stored_hashes: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)

    # -- Timestamp --
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # -- Relationships --
    selection: Mapped["Selection"] = relationship(
        "Selection",
        back_populates="test_results",
    )

    def __repr__(self) -> str:
        return (
            f"<TestGenResult id={self.id} "
            f"selection_id={self.selection_id} "
            f"model={self.model_name!r}>"
        )
