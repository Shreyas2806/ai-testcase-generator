import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.node import Node as DBNode
from app.models.selection import Selection
from app.models.selection_node import SelectionNode
from app.models.version import Version

logger = logging.getLogger(__name__)


def create_selection(
    db: Session,
    version_id: int,
    name: str,
    node_ids: list[int],
) -> Selection:
    """
    Business logic to create a Selection.

    Validations:
    1. The target Version must exist.
    2. All provided node_ids must exist AND belong to the target Version.
    3. Duplicate node_ids in the input list are ignored (de-duplicated).
    """
    # 1. Validate Version exists
    version = db.query(Version).filter(Version.id == version_id).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version id={version_id} not found.",
        )

    # 2. De-duplicate input node IDs
    unique_node_ids = list(set(node_ids))
    if not unique_node_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A selection must contain at least one node.",
        )

    # 3. Fetch the requested nodes from the database
    # We filter by both the node IDs AND the version_id to ensure
    # the user isn't trying to select nodes from a different version.
    valid_nodes = (
        db.query(DBNode)
        .filter(DBNode.id.in_(unique_node_ids))
        .filter(DBNode.version_id == version_id)
        .all()
    )

    # 4. Check if we found exactly the number of unique nodes we asked for
    if len(valid_nodes) != len(unique_node_ids):
        valid_ids_set = {n.id for n in valid_nodes}
        invalid_ids = set(unique_node_ids) - valid_ids_set
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid node IDs: {invalid_ids}. "
                f"Ensure they exist and belong to version_id={version_id}."
            ),
        )

    # 5. Create the Selection record
    selection = Selection(version_id=version_id, name=name)
    db.add(selection)
    db.flush()  # Populate selection.id for the junction rows

    # 6. Create the junction rows (SelectionNode)
    for node_id in unique_node_ids:
        junction = SelectionNode(selection_id=selection.id, node_id=node_id)
        db.add(junction)

    # Note: caller is responsible for db.commit()
    return selection
