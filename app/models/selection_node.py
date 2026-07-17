from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class SelectionNode(Base):
    """
    Junction table linking Selections to Nodes (many-to-many).

    Modelled as a full ORM class (not a plain association table) because:
    - It carries its own metadata (created_at).
    - It may be extended with additional columns in future phases.
    - Individual junction rows may need to be addressed directly by the API.

    Constraints:
        uq_selection_node: prevents duplicate (selection_id, node_id) pairs.

    Relationships:
        selection : the parent Selection (many-to-one)
        node      : the referenced Node (many-to-one)
    """

    __tablename__ = "selection_nodes"

    # Enforce uniqueness at the DB level — a node can only appear once
    # in a given selection.
    __table_args__ = (
        UniqueConstraint("selection_id", "node_id", name="uq_selection_node"),
    )

    # -- Primary Key --
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # -- Foreign Keys --
    selection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("selections.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )

    # -- Timestamp --
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # -- Relationships --
    selection: Mapped["Selection"] = relationship(
        "Selection",
        back_populates="selection_nodes",
    )
    node: Mapped["Node"] = relationship(
        "Node",
        back_populates="selection_nodes",
    )

    def __repr__(self) -> str:
        return (
            f"<SelectionNode id={self.id} "
            f"selection_id={self.selection_id} "
            f"node_id={self.node_id}>"
        )
