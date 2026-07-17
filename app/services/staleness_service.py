"""
Staleness Service — Checks whether generated test cases are still valid (current)
relative to any edits made to the source document nodes since generation.

Why Hashing Is Useful
---------------------
Comparing full text blocks (headings, body content, code snippets) on every request
is computationally expensive and consumes significant database/network bandwidth.
By storing a pre-computed SHA-256 hash of each node's content, we reduce the
comparison to a simple string equality check of 64-character hex digests. This allows
instant, lightweight staleness checks.

SHA-256 Comparison
------------------
At generation time, the hash of each node in the selection is stored inside the
`TestGenResult` metadata (`stored_hashes`).
When checking status:
  - We fetch the current `content_hash` for each corresponding Node from the DB.
  - We compare `stored_hash` directly with the `current_hash`.
  - A mismatch guarantees that the content has changed, making the test suite STALE.

Stale Detection Algorithm
-------------------------
1. Load `TestGenResult` from the database. If not found, raise a 404 error.
2. Retrieve the `stored_hashes` dictionary (mapping `node_id` -> `stored_hash`).
3. Loop through all `node_id` keys in `stored_hashes`:
     - Load the current state of the Node from the database.
     - Case A: Node no longer exists in the DB -> Node was deleted. Record it as stale.
     - Case B: Current `content_hash` != `stored_hash` -> Node was updated. Record it as stale.
     - Case C: Hashes match -> Node is unchanged.
4. If any node was changed or deleted:
     - Return status "STALE" along with details of the affected nodes.
   Else:
     - Return status "CURRENT".
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.node import Node as DBNode
from app.models.test_gen_result import TestGenResult

logger = logging.getLogger(__name__)


def check_test_run_staleness(test_run_id: int, db: Session) -> dict:
    """
    Evaluate if an AI-generated test run is STALE or CURRENT.

    Compares the stored node hashes at the time of generation against
    the current content hashes in the database.
    """
    # 1. Fetch TestGenResult
    result = db.query(TestGenResult).filter(TestGenResult.id == test_run_id).first()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test run id={test_run_id} not found.",
        )

    stored_hashes = result.stored_hashes or {}
    if not stored_hashes:
        # If no hashes were stored at generation time, default to CURRENT
        return {"status": "CURRENT"}

    changed_nodes = []

    # 2. Iterate through all referenced nodes and compare hashes
    for node_id_str, stored_hash in stored_hashes.items():
        node_id = int(node_id_str)
        node = db.query(DBNode).filter(DBNode.id == node_id).first()

        if not node:
            # Case A: Node has been deleted from the database
            changed_nodes.append(
                {
                    "node_id": node_id,
                    "heading": "Deleted Section",
                    "stored_hash": stored_hash,
                    "current_hash": None,
                    "reason": "deleted",
                }
            )
        elif (node.content_hash or "") != stored_hash:
            # Case B: Content has been modified since generation
            changed_nodes.append(
                {
                    "node_id": node.id,
                    "heading": node.heading,
                    "stored_hash": stored_hash,
                    "current_hash": node.content_hash or "",
                    "reason": "changed",
                }
            )

    # 3. Formulate the response
    if changed_nodes:
        logger.info(
            "Test run id=%d marked STALE due to %d changed node(s)",
            test_run_id, len(changed_nodes),
        )
        return {
            "status": "STALE",
            "changed_nodes": changed_nodes,
        }

    logger.info("Test run id=%d is CURRENT", test_run_id)
    return {"status": "CURRENT"}
