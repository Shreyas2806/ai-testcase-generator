import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.schemas.testcase import NodeTestsResponse, SelectionTestsResponse, TestStalenessResponse
from app.services.testcase_service import get_tests_for_node, get_tests_for_selection
from app.services.staleness_service import check_test_run_staleness

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Test Cases"])


# ---------------------------------------------------------------------------
# GET /selections/{id}/tests
# ---------------------------------------------------------------------------

@router.get(
    "/selections/{selection_id}/tests",
    response_model=SelectionTestsResponse,
    summary="Get all generated test runs for a selection",
    description=(
        "Returns every AI generation run for the specified selection, "
        "ordered from most recent to oldest. Each run contains the full "
        "list of generated test cases. Supports pagination via `page` and "
        "`page_size` query parameters."
    ),
)
def get_selection_tests(
    selection_id: int,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(default=10, ge=1, le=50, description="Items per page (max 50)."),
    db: Session = Depends(get_db),
) -> SelectionTestsResponse:
    """
    Request flow:
      1. FastAPI resolves selection_id from the URL path.
      2. page and page_size come from query params with validation
         (ge=1 prevents negative pages; le=50 caps result size).
      3. Delegates all query logic to testcase_service.
      4. Service raises 404 if the selection doesn't exist.
      5. Returns SelectionTestsResponse — empty runs list if no tests yet.

    Why not 404 for empty runs?
      A selection with no generated tests is a valid state.
      Returning 404 would be incorrect — the resource exists.
      We return 200 with total_runs=0 and runs=[].
    """
    return get_tests_for_selection(
        selection_id=selection_id,
        db=db,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /nodes/{id}/tests
# ---------------------------------------------------------------------------

@router.get(
    "/nodes/{node_id}/tests",
    response_model=NodeTestsResponse,
    summary="Get all generated test runs referencing a node",
    description=(
        "Returns every AI generation run from any selection that contains "
        "the specified node. This is useful for tracing which test cases "
        "cover a particular content node. Supports pagination."
    ),
)
def get_node_tests(
    node_id: int,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)."),
    page_size: int = Query(default=10, ge=1, le=50, description="Items per page (max 50)."),
    db: Session = Depends(get_db),
) -> NodeTestsResponse:
    """
    Request flow:
      1. FastAPI resolves node_id from the URL path.
      2. Delegates to testcase_service.get_tests_for_node.
      3. Service validates node exists (404 if not).
      4. Service traverses Node -> SelectionNode -> Selection -> TestGenResult.
      5. Returns NodeTestsResponse with all matching runs.
    """
    return get_tests_for_node(
        node_id=node_id,
        db=db,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /tests/{test_run_id}/status
# ---------------------------------------------------------------------------

@router.get(
    "/tests/{test_run_id}/status",
    response_model=TestStalenessResponse,
    summary="Check if a generated test run is stale",
    description=(
        "Compares the hashes of the nodes at the time of test generation "
        "against their current content hashes in the database. "
        "If any node has changed or been deleted, returns status 'STALE' "
        "with details of the changes. Otherwise, returns status 'CURRENT'."
    ),
)
def get_test_run_status(
    test_run_id: int,
    db: Session = Depends(get_db),
) -> TestStalenessResponse:
    """
    Request flow:
      1. FastAPI resolves test_run_id from the URL path.
      2. Calls check_test_run_staleness to verify hashes.
      3. Returns the status and changed nodes (if any).
    """
    data = check_test_run_staleness(test_run_id=test_run_id, db=db)
    return TestStalenessResponse(**data)
