"""
Testcase retrieval service.

All queries use SQLAlchemy ORM joins — no raw SQL.

Query patterns explained:

GET /selections/{id}/tests
--------------------------
  SELECT * FROM test_gen_results
  WHERE selection_id = ?
  ORDER BY created_at DESC
  LIMIT ? OFFSET ?

  We also fetch the Selection row in the same round-trip using
  SQLAlchemy's joined-load (relationship access triggers it).
  This avoids N+1 queries.

GET /nodes/{id}/tests
---------------------
  We need to walk:
    Node → SelectionNode → Selection → TestGenResult

  Step 1: Collect all selection_ids that include this node.
          SELECT selection_id FROM selection_nodes WHERE node_id = ?

  Step 2: Query test_gen_results for those selection_ids,
          joined with the Selection for its name.
          ORDER BY created_at DESC with pagination.

  Both steps are done with ORM joins — no raw SQL.
"""

import json
import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.node import Node as DBNode
from app.models.selection import Selection
from app.models.selection_node import SelectionNode
from app.models.test_gen_result import TestGenResult
from app.schemas.testcase import (
    NodeTestRunResponse,
    NodeTestsResponse,
    SelectionTestsResponse,
    TestCaseItem,
    TestRunResponse,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: parse stored JSON into TestCaseItem list
# ---------------------------------------------------------------------------

def _parse_test_cases(generated_json: str) -> list[TestCaseItem]:
    """
    Parse the stored Gemini JSON string into a list of TestCaseItem objects.

    The JSON was already validated by Pydantic at generation time, so this
    should always succeed. We still wrap it defensively.
    """
    try:
        data = json.loads(generated_json)
        return [TestCaseItem(**tc) for tc in data.get("test_cases", [])]
    except Exception as exc:
        logger.error("Failed to parse stored test JSON: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Endpoint 1: GET /selections/{id}/tests
# ---------------------------------------------------------------------------

def get_tests_for_selection(
    selection_id: int,
    db: Session,
    page: int = 1,
    page_size: int = 10,
) -> SelectionTestsResponse:
    """
    Retrieve all generation runs for a given selection, paginated.

    Query strategy:
        1. Validate the selection exists (1 query).
        2. Count total runs (1 query — needed for has_more).
        3. Fetch paginated runs with joinedload on selection
           to avoid N+1 (1 query with LEFT JOIN).
        Total: 3 queries regardless of result size.
    """
    # 1. Validate selection exists
    selection = (
        db.query(Selection)
        .filter(Selection.id == selection_id)
        .first()
    )
    if not selection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selection id={selection_id} not found.",
        )

    # 2. Count total runs
    total = (
        db.query(TestGenResult)
        .filter(TestGenResult.selection_id == selection_id)
        .count()
    )

    if total == 0:
        return SelectionTestsResponse(
            selection_id=selection.id,
            selection_name=selection.name,
            version_id=selection.version_id,
            total_runs=0,
            runs=[],
        )

    # 3. Fetch paginated runs (most recent first)
    offset = (page - 1) * page_size
    rows: list[TestGenResult] = (
        db.query(TestGenResult)
        .filter(TestGenResult.selection_id == selection_id)
        .order_by(TestGenResult.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # Build response objects
    runs = [
        TestRunResponse(
            result_id=row.id,
            generated_at=row.created_at,
            model=row.model_name,
            retry_count=row.retry_count,
            tests=_parse_test_cases(row.generated_json),
        )
        for row in rows
    ]

    return SelectionTestsResponse(
        selection_id=selection.id,
        selection_name=selection.name,
        version_id=selection.version_id,
        total_runs=total,
        runs=runs,
    )


# ---------------------------------------------------------------------------
# Endpoint 2: GET /nodes/{id}/tests
# ---------------------------------------------------------------------------

def get_tests_for_node(
    node_id: int,
    db: Session,
    page: int = 1,
    page_size: int = 10,
) -> NodeTestsResponse:
    """
    Retrieve all generation runs that reference a given node.

    A node can appear in multiple selections; each selection can have
    multiple runs. We flatten all of them, ordered newest-first.

    Query strategy:
        1. Validate node exists (1 query).
        2. Collect all selection_ids containing this node via
           SelectionNode join (1 query).
        3. Count total runs across those selections (1 query).
        4. Fetch paginated runs joined with Selection for name (1 query).
        Total: 4 queries regardless of how many selections/runs exist.
    """
    # 1. Validate node exists
    node = db.query(DBNode).filter(DBNode.id == node_id).first()
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node id={node_id} not found.",
        )

    # 2. Get all selection_ids that contain this node
    selection_ids: list[int] = [
        row.selection_id
        for row in db.query(SelectionNode.selection_id)
        .filter(SelectionNode.node_id == node_id)
        .all()
    ]

    if not selection_ids:
        return NodeTestsResponse(
            node_id=node_id,
            node_heading=node.heading,
            total_runs=0,
            runs=[],
        )

    # 3. Count total runs across all those selections
    total = (
        db.query(TestGenResult)
        .filter(TestGenResult.selection_id.in_(selection_ids))
        .count()
    )

    if total == 0:
        return NodeTestsResponse(
            node_id=node_id,
            node_heading=node.heading,
            total_runs=0,
            runs=[],
        )

    # 4. Fetch paginated runs — JOIN with Selection to get selection name
    #    joinedload tells SQLAlchemy to LEFT JOIN selection in the same query
    #    instead of issuing a separate SELECT per row (avoids N+1).
    offset = (page - 1) * page_size
    rows: list[TestGenResult] = (
        db.query(TestGenResult)
        .options(joinedload(TestGenResult.selection))
        .filter(TestGenResult.selection_id.in_(selection_ids))
        .order_by(TestGenResult.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    runs = [
        NodeTestRunResponse(
            result_id=row.id,
            selection_id=row.selection_id,
            selection_name=row.selection.name,
            generated_at=row.created_at,
            model=row.model_name,
            tests=_parse_test_cases(row.generated_json),
        )
        for row in rows
    ]

    return NodeTestsResponse(
        node_id=node_id,
        node_heading=node.heading,
        total_runs=total,
        runs=runs,
    )
