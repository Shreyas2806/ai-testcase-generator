from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Selection(Base):
    """
    Represents a named, user-defined grouping of Nodes for test purposes.

    A Selection holds references to one or more Nodes (via SelectionNode)
    and is always tied to a specific Version.

    Relationships:
        version         : the Version this Selection belongs to
        selection_nodes : junction rows linking this Selection to Nodes
    """

    __tablename__ = "selections"

    # -- Primary Key --
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # -- Foreign Keys --
    version_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # -- Fields --
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- Timestamps --
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
    version: Mapped["Version"] = relationship(
        "Version",
        back_populates="selections",
    )

    # cascade="all, delete-orphan": removing a Selection cleans up its
    # SelectionNode junction rows automatically.
    selection_nodes: Mapped[list["SelectionNode"]] = relationship(
        "SelectionNode",
        back_populates="selection",
        cascade="all, delete-orphan",
    )

    # AI-generated test suites for this selection
    test_results: Mapped[list["TestGenResult"]] = relationship(
        "TestGenResult",
        back_populates="selection",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Selection id={self.id} name={self.name!r}>"
