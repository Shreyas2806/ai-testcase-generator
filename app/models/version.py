from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Version(Base):
    """
    Represents a specific revision of a Document.

    Versions are immutable snapshots — once a Version is created, its
    content does not change. If a document is re-processed, a new Version
    row is inserted instead of updating the existing one.

    Relationships:
        document  : the parent Document (many-to-one)
        nodes     : the parsed structural elements of this version (one-to-many)
    """

    __tablename__ = "versions"

    # -- Primary Key --
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # -- Foreign Key --
    # ondelete="CASCADE" keeps the DB-level constraint in sync with SQLAlchemy's
    # ORM-level cascade. Without this, the DB engine would reject deletes even
    # though SQLAlchemy's cascade is set correctly.
    document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    # -- Fields --
    # Monotonically increasing per document. e.g. 1, 2, 3...
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Optional human-readable label e.g. "v1.0-final", "draft"
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # -- Timestamp --
    # No updated_at — versions are immutable snapshots.
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # -- Relationships --
    # back_populates="versions" links to Document.versions (in document.py).
    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="versions",
    )

    # cascade="all, delete-orphan": deleting a Version deletes all its Nodes.
    # A version contains a tree of nodes
    nodes: Mapped[list["Node"]] = relationship(
        "Node",
        back_populates="version",
        cascade="all, delete-orphan",
    )

    # A version can have multiple selections
    selections: Mapped[list["Selection"]] = relationship(
        "Selection",
        back_populates="version",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Version id={self.id} "
            f"document_id={self.document_id} "
            f"version_number={self.version_number}>"
        )
