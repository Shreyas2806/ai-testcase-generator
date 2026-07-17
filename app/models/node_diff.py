from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class NodeDiff(Base):
    """
    Records the diff result for a single node between two Versions.

    One NodeDiff row is created per node comparison during a version diff run.
    At most one of v1_node_id / v2_node_id is NULL:
        - status="new"       : v1_node_id is NULL  (node did not exist in v1)
        - status="deleted"   : v2_node_id is NULL  (node no longer exists in v2)
        - status="changed"   : both FKs set, hashes differ
        - status="unchanged" : both FKs set, hashes match

    Relationships:
        v1_node : the Version-1 Node (None for "new" nodes)
        v2_node : the Version-2 Node (None for "deleted" nodes)
    """

    __tablename__ = "node_diffs"

    # -- Primary Key --
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # -- Version references (for querying all diffs in a run) --
    version1_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False
    )
    version2_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False
    )

    # -- Node references --
    # NULL when status="new" (no counterpart in v1)
    v1_node_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True
    )
    # NULL when status="deleted" (no counterpart in v2)
    v2_node_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True
    )

    # -- Diff result --
    # One of: "unchanged" | "changed" | "new" | "deleted"
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Human-readable description of what changed (populated for "changed" status)
    diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The full heading path used to match this node across versions
    # e.g. "Introduction > Purpose > Overview"
    node_path: Mapped[str] = mapped_column(Text, nullable=False)

    # -- Timestamp --
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<NodeDiff id={self.id} "
            f"status={self.status!r} "
            f"v1={self.v1_node_id} v2={self.v2_node_id}>"
        )
