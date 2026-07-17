import hashlib
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.node import Node as DBNode
from app.models.version import Version
from app.services.hierarchy_builder import Node as TreeNode

logger = logging.getLogger(__name__)


def _sha256(text: str) -> str:
    """Return the SHA-256 hex digest of a UTF-8 encoded string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentStorageService:
    """
    Persists a parsed document hierarchy to the database.

    All write operations are performed within a single transaction managed
    by the caller's SQLAlchemy Session. The caller is responsible for
    calling db.commit() on success or db.rollback() on failure.

    Typical usage:
        service = DocumentStorageService(db)
        try:
            doc     = service.save_document(name, file_path)
            version = service.save_version(doc.id, label="v1")
            nodes   = service.save_tree(tree_roots, version.id)
            db.commit()
        except Exception:
            db.rollback()
            raise
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_document(
        self,
        name: str,
        file_path: str | Path | None = None,
        description: str | None = None,
    ) -> Document:
        """
        Retrieve an existing Document by file_path, or create a new one.

        The "get-or-create" pattern prevents duplicate Document rows when
        the same file is re-uploaded or re-parsed.

        Args:
            name        : Human-readable document name.
            file_path   : Absolute path to the source PDF (optional).
            description : Optional description.

        Returns:
            The existing or newly created Document ORM object.
        """
        normalized_path = str(file_path) if file_path else None

        # -- Duplicate check: same file_path = same document --
        if normalized_path:
            existing = (
                self._db.query(Document)
                .filter(Document.file_path == normalized_path)
                .first()
            )
            if existing:
                logger.info(
                    "Document already exists (id=%d): %s", existing.id, normalized_path
                )
                return existing

        doc = Document(
            name=name,
            file_path=normalized_path,
            description=description,
        )
        self._db.add(doc)
        # flush() sends the INSERT to the DB within the current transaction
        # and populates doc.id — but does NOT commit. We need the ID now
        # so save_version() can reference it via the foreign key.
        self._db.flush()

        logger.info("Saved Document id=%d name=%r", doc.id, doc.name)
        return doc

    def save_version(
        self,
        document_id: int,
        label: str | None = None,
    ) -> Version:
        """
        Create a new Version for the given Document.

        The version_number is auto-calculated as (max existing + 1),
        ensuring monotonic ordering without gaps.

        Args:
            document_id : FK reference to the parent Document.
            label       : Optional tag e.g. "v1.0-final", "draft".

        Returns:
            The newly created Version ORM object.
        """
        # Calculate next version number
        from sqlalchemy import func

        max_version = (
            self._db.query(func.max(Version.version_number))
            .filter(Version.document_id == document_id)
            .scalar()
        )
        next_version_number = (max_version or 0) + 1

        version = Version(
            document_id=document_id,
            version_number=next_version_number,
            label=label,
        )
        self._db.add(version)
        self._db.flush()  # populate version.id before tree insertion

        logger.info(
            "Saved Version id=%d (v%d) for Document id=%d",
            version.id,
            version.version_number,
            document_id,
        )
        return version

    def save_tree(
        self,
        roots: list[TreeNode],
        version_id: int,
    ) -> list[DBNode]:
        """
        Recursively persist the full Node tree to the database.

        Walks the HierarchyBuilder tree depth-first. Each TreeNode becomes
        a DBNode row. Parent-child links are encoded via parent_id FK.

        Args:
            roots      : Top-level nodes from HierarchyBuilder.build_tree().
            version_id : FK reference to the parent Version.

        Returns:
            The list of saved top-level DBNode objects (with all children
            already flushed and carrying their assigned database IDs).
        """
        saved_roots: list[DBNode] = []
        for order, root in enumerate(roots):
            db_node = self._save_node_recursive(
                tree_node=root,
                version_id=version_id,
                parent_db_id=None,  # root nodes have no parent
                order_index=order,
            )
            saved_roots.append(db_node)

        logger.info(
            "Saved tree: %d root node(s) into Version id=%d",
            len(saved_roots),
            version_id,
        )
        return saved_roots

    # ------------------------------------------------------------------
    # Private: recursive node insertion
    # ------------------------------------------------------------------

    def _save_node_recursive(
        self,
        tree_node: TreeNode,
        version_id: int,
        parent_db_id: int | None,
        order_index: int,
    ) -> DBNode:
        """
        Insert one Node row, then recursively insert all its children.

        The recursion depth equals the maximum tree depth. For typical
        documents this is 3–6 levels — well within Python's default
        recursion limit of 1000.

        Args:
            tree_node    : The HierarchyBuilder Node being persisted.
            version_id   : FK to the parent Version row.
            parent_db_id : DB primary key of the parent DBNode row (None = root).
            order_index  : Position among siblings (0-indexed).

        Returns:
            The saved DBNode with its id populated after flush().
        """
        content = tree_node.body if tree_node.body else None
        content_hash = _sha256(content) if content else None

        db_node = DBNode(
            version_id=version_id,
            parent_id=parent_db_id,
            heading=tree_node.heading,
            content=content,
            content_hash=content_hash,
            node_type=tree_node.block_type,
            page_number=tree_node.page,
            order_index=order_index,
        )
        self._db.add(db_node)

        # Flush immediately to obtain db_node.id before processing children.
        # Children reference this id via their parent_id FK.
        self._db.flush()

        logger.debug(
            "  Saved Node id=%d parent_id=%s heading=%r",
            db_node.id,
            parent_db_id,
            tree_node.heading[:40],
        )

        # Recurse into children
        for child_order, child in enumerate(tree_node.children):
            self._save_node_recursive(
                tree_node=child,
                version_id=version_id,
                parent_db_id=db_node.id,  # pass this node's DB id as parent
                order_index=child_order,
            )

        return db_node
