from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Node(Base):
    """
    Represents a single structural element within a document Version.

    Nodes form a tree: each Node may have a parent Node (via parent_id)
    and zero or more children. The root nodes of the tree have parent_id=NULL.

    Relationships:
        version         : the parent Version (many-to-one)
        parent          : the parent Node in the hierarchy (self-referential, nullable)
        children        : child Nodes in the hierarchy (self-referential)
        selection_nodes : junction rows linking this Node to Selections
    """

    __tablename__ = "nodes"

    # -- Primary Key --
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # -- Foreign Keys --
    version_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Self-referential FK — NULL means this is a root node within the version.
    parent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=True,
    )

    # -- Fields --
    # The section title text (e.g. "Introduction", "System Overview")
    heading: Mapped[str] = mapped_column(Text, nullable=False)

    # The body content accumulated under this heading (paragraphs, lists)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SHA-256 hex digest of the content field. Used for deduplication
    # and integrity verification. NULL when content is empty.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Categorises the node type: "heading" | "subheading" | "paragraph" etc.
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Source page in the original document (1-indexed)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Position within the version — used to reconstruct document reading order
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # -- Timestamp --
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # -- Relationships --
    version: Mapped["Version"] = relationship(
        "Version",
        back_populates="nodes",
    )

    # Self-referential: a node's parent (None for root nodes)
    parent: Mapped["Node | None"] = relationship(
        "Node",
        back_populates="children",
        remote_side="Node.id",  # "remote_side" tells SA which side is the "one"
    )

    # Self-referential: a node's direct children
    children: Mapped[list["Node"]] = relationship(
        "Node",
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    # Junction table link to Selections
    selection_nodes: Mapped[list["SelectionNode"]] = relationship(
        "SelectionNode",
        back_populates="node",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Node id={self.id} "
            f"version_id={self.version_id} "
            f"parent_id={self.parent_id} "
            f"type={self.node_type!r} "
            f"heading={self.heading[:30]!r}>"
        )
