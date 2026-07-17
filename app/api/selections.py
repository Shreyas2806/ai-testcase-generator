import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.selection import Selection
from app.models.test_gen_result import TestGenResult
from app.schemas.selection import (
    SelectionCreate,
    SelectionResponse,
    SelectionNodeResponse,
    TestGenResponse,
    TestCaseItemResponse,
)
from app.services.selection_service import create_selection
from app.services.llm_service import generate_test_cases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/selections", tags=["Selections"])


# ---------------------------------------------------------------------------
# Helper: ORM → Response schema
# ---------------------------------------------------------------------------

def _to_selection_response(selection: Selection) -> SelectionResponse:
    nodes_summary = [
        SelectionNodeResponse(
            node_id=jn.node.id,
            heading=jn.node.heading,
            node_type=jn.node.node_type,
        )
        for jn in selection.selection_nodes
    ]
    return SelectionResponse(
        id=selection.id,
        version_id=selection.version_id,
        name=selection.name,
        description=selection.description,
        nodes=nodes_summary,
    )


# ---------------------------------------------------------------------------
# POST /selections
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=SelectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new selection",
    description=(
        "Creates a named selection of nodes tied to a specific document version. "
        "Validates that the version exists and all requested nodes belong to it. "
        "Duplicate node IDs in the input are silently de-duplicated."
    ),
)
def create_selection_endpoint(
    payload: SelectionCreate,
    db: Session = Depends(get_db),
) -> SelectionResponse:
    """
    Request flow:
      1. Receive JSON payload (version_id, name, node_ids) via SelectionCreate.
      2. Delegate to selection_service for validation + DB inserts.
      3. Commit on success, rollback on any error.
      4. Return SelectionResponse with a flat list of selected nodes.
    """
    try:
        selection = create_selection(
            db=db,
            version_id=payload.version_id,
            name=payload.name,
            node_ids=payload.node_ids,
        )
        db.commit()
        db.refresh(selection)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create selection: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the selection.",
        )

    return _to_selection_response(selection)


# ---------------------------------------------------------------------------
# GET /selections
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[SelectionResponse],
    summary="List all selections",
)
def list_selections(db: Session = Depends(get_db)) -> list[SelectionResponse]:
    selections = db.query(Selection).order_by(Selection.id).all()
    return [_to_selection_response(s) for s in selections]


# ---------------------------------------------------------------------------
# GET /selections/{id}
# ---------------------------------------------------------------------------

@router.get(
    "/{selection_id}",
    response_model=SelectionResponse,
    summary="Get a selection by ID",
)
def get_selection(
    selection_id: int,
    db: Session = Depends(get_db),
) -> SelectionResponse:
    selection = db.query(Selection).filter(Selection.id == selection_id).first()
    if not selection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selection id={selection_id} not found.",
        )
    return _to_selection_response(selection)


# ---------------------------------------------------------------------------
# DELETE /selections/{id}
# ---------------------------------------------------------------------------

@router.delete(
    "/{selection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a selection",
    description="Deletes the selection and all its node mappings (cascade).",
)
def delete_selection(
    selection_id: int,
    db: Session = Depends(get_db),
) -> None:
    selection = db.query(Selection).filter(Selection.id == selection_id).first()
    if not selection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selection id={selection_id} not found.",
        )
    db.delete(selection)
    db.commit()


# ---------------------------------------------------------------------------
# POST /selections/{id}/generate-tests
# ---------------------------------------------------------------------------

@router.post(
    "/{selection_id}/generate-tests",
    response_model=TestGenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate AI test cases for a selection",
    description=(
        "Feeds the selected node content to Google Gemini and generates "
        "exactly 5 structured QA test cases. Results are validated with "
        "Pydantic and stored in the database. Retries up to 3 times if "
        "Gemini returns invalid JSON."
    ),
    tags=["AI Generation"],
)
def generate_tests(
    selection_id: int,
    db: Session = Depends(get_db),
) -> TestGenResponse:
    """
    Request flow:
      1. Call llm_service.generate_test_cases with the selection_id.
      2. The service fetches nodes, builds prompt, calls Gemini, validates JSON.
      3. On success, the result is flushed (not yet committed) and returned.
      4. We commit the transaction here and parse the stored JSON for the response.
    """
    try:
        result: TestGenResult = generate_test_cases(selection_id=selection_id, db=db)
        db.commit()
        db.refresh(result)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("generate-tests failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during test generation: {exc}",
        )

    # Parse the stored JSON and build the response
    parsed = json.loads(result.generated_json)
    test_cases = [TestCaseItemResponse(**tc) for tc in parsed["test_cases"]]

    return TestGenResponse(
        result_id=result.id,
        selection_id=result.selection_id,
        model_name=result.model_name,
        retry_count=result.retry_count,
        test_cases=test_cases,
    )
