from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Document(Base):
    """
    Represents a source document (e.g. a PDF file) in the system.

    A Document is the top-level entity. It can have multiple Versions,
    allowing the system to track changes across document revisions.
    """

    __tablename__ = "documents"

    # -- Primary Key --
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # -- Fields --
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Text for longer strings — no length limit in SQLite
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Nullable: file_path is set after the file is uploaded/processed
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # -- Timestamps --
    # timezone.utc ensures all timestamps are stored in UTC.
    # default= fires on INSERT; onupdate= fires on UPDATE.
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # -- Relationships --
    # back_populates="document" links to Version.document (defined in version.py).
    # cascade="all, delete-orphan" means deleting a Document also deletes
    # all its Versions automatically — correct behaviour for owned children.
    versions: Mapped[list["Version"]] = relationship(
        "Version",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} name={self.name!r}>"
