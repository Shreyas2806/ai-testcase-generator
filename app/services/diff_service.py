import difflib
import logging

from sqlalchemy.orm import Session

from app.models.node import Node as DBNode
from app.models.node_diff import NodeDiff

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path building
# ---------------------------------------------------------------------------

def _build_path(node: DBNode, node_index: dict[int, DBNode]) -> str:
    """
    Build the full ancestry path for a node using a pre-built id→node index.

    Example: "Introduction > Purpose > Overview"

    Using an index avoids repeated DB queries when building paths for every
    node in a version (O(n) total queries instead of O(n × depth)).
    """
    parts: list[str] = []
    current = node
    while current is not None:
        parts.append(current.heading.strip())
        current = node_index.get(current.parent_id) if current.parent_id else None
    parts.reverse()
    return " > ".join(parts)


def _build_path_map(
    version_id: int, db: Session
) -> dict[str, DBNode]:
    """
    Return a dict mapping normalized heading path → DBNode for all nodes
    in the given version.
    """
    nodes = db.query(DBNode).filter(DBNode.version_id == version_id).all()
    node_index: dict[int, DBNode] = {n.id: n for n in nodes}
    return {
        _build_path(node, node_index).lower(): node  # lowercase for case-insensitive match
        for node in nodes
    }


# ---------------------------------------------------------------------------
# Diff summary generation
# ---------------------------------------------------------------------------

def _generate_diff_summary(old_content: str | None, new_content: str | None) -> str:
    """
    Generate a human-readable summary of what changed between two content strings.

    For short content: show inline diff.
    For longer content: show character-level change count.
    """
    old = old_content or ""
    new = new_content or ""

    if not old and new:
        return "Content added (was empty)."
    if old and not new:
        return "Content removed (now empty)."

    # Use difflib to find changed tokens
    old_words = old.split()
    new_words = new.split()

    matcher = difflib.SequenceMatcher(None, old_words, new_words)
    opcodes = matcher.get_opcodes()

    changes: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "replace":
            old_snippet = " ".join(old_words[i1:i2])[:60]
            new_snippet = " ".join(new_words[j1:j2])[:60]
            changes.append(f'"{old_snippet}" -> "{new_snippet}"')
        elif tag == "delete":
            snippet = " ".join(old_words[i1:i2])[:60]
            changes.append(f'Removed: "{snippet}"')
        elif tag == "insert":
            snippet = " ".join(new_words[j1:j2])[:60]
            changes.append(f'Added: "{snippet}"')

    if not changes:
        return "Content reformatted (no semantic change detected)."

    # Return up to 3 most significant changes
    summary = "; ".join(changes[:3])
    if len(changes) > 3:
        summary += f" ... and {len(changes) - 3} more change(s)."
    return summary


# ---------------------------------------------------------------------------
# Core diff computation
# ---------------------------------------------------------------------------

def compute_diff(
    version1_id: int,
    version2_id: int,
    db: Session,
) -> list[NodeDiff]:
    """
    Compare all nodes in version1 against version2 and persist NodeDiff rows.

    Algorithm:
        1. Build path→node maps for both versions.
        2. Walk all v2 paths:
           - Found in v1 + same hash  → UNCHANGED
           - Found in v1 + diff hash  → CHANGED (generate summary)
           - Not found in v1          → NEW
        3. Walk all v1 paths not seen in step 2 → DELETED

    All NodeDiff rows are flushed but NOT committed — caller commits.

    Returns:
        List of created NodeDiff objects.
    """
    logger.info(
        "Computing diff: version %d -> version %d", version1_id, version2_id
    )

    v1_map = _build_path_map(version1_id, db)
    v2_map = _build_path_map(version2_id, db)

    logger.info("v1 nodes: %d  |  v2 nodes: %d", len(v1_map), len(v2_map))

    diffs: list[NodeDiff] = []
    visited_v1_paths: set[str] = set()

    # -- Compare v2 nodes against v1 --
    for path, v2_node in v2_map.items():
        v1_node = v1_map.get(path)

        if v1_node is None:
            # Node exists in v2 but not v1 → NEW
            diff = NodeDiff(
                version1_id=version1_id,
                version2_id=version2_id,
                v1_node_id=None,
                v2_node_id=v2_node.id,
                status="new",
                diff_summary="New section added in this version.",
                node_path=path,
            )
        elif v1_node.content_hash == v2_node.content_hash:
            # Same path, same content → UNCHANGED
            diff = NodeDiff(
                version1_id=version1_id,
                version2_id=version2_id,
                v1_node_id=v1_node.id,
                v2_node_id=v2_node.id,
                status="unchanged",
                diff_summary="Content is identical to the previous version.",
                node_path=path,
            )
            visited_v1_paths.add(path)
        else:
            # Same path, different content → CHANGED
            summary = _generate_diff_summary(v1_node.content, v2_node.content)
            diff = NodeDiff(
                version1_id=version1_id,
                version2_id=version2_id,
                v1_node_id=v1_node.id,
                v2_node_id=v2_node.id,
                status="changed",
                diff_summary=summary,
                node_path=path,
            )
            visited_v1_paths.add(path)

        db.add(diff)
        diffs.append(diff)

    # -- v1 nodes not matched by any v2 node → DELETED --
    for path, v1_node in v1_map.items():
        if path not in v2_map:
            diff = NodeDiff(
                version1_id=version1_id,
                version2_id=version2_id,
                v1_node_id=v1_node.id,
                v2_node_id=None,
                status="deleted",
                diff_summary="Section was removed in this version.",
                node_path=path,
            )
            db.add(diff)
            diffs.append(diff)

    db.flush()

    # Log summary
    counts = {"new": 0, "changed": 0, "unchanged": 0, "deleted": 0}
    for d in diffs:
        counts[d.status] += 1
    logger.info("Diff result: %s", counts)

    return diffs


# ---------------------------------------------------------------------------
# Query: get diff for a single node
# ---------------------------------------------------------------------------

def get_node_diff(node_id: int, db: Session) -> NodeDiff | None:
    """
    Retrieve the NodeDiff record for a given node ID.

    Checks both v2_node_id (for new/changed/unchanged nodes) and
    v1_node_id (for deleted nodes).
    """
    result = (
        db.query(NodeDiff)
        .filter(
            (NodeDiff.v2_node_id == node_id) | (NodeDiff.v1_node_id == node_id)
        )
        .order_by(NodeDiff.id.desc())  # most recent diff first
        .first()
    )
    return result
