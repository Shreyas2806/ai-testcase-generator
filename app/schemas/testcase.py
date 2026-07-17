"""
Pydantic schemas for test case retrieval endpoints.

Hierarchy:
    SelectionTestsResponse          ← GET /selections/{id}/tests
        └── TestRunResponse         ← one generation run
                └── TestCaseItem    ← one test case

    NodeTestsResponse               ← GET /nodes/{id}/tests
        └── NodeTestRunResponse     ← run + which selection it came from
                └── TestCaseItem
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared: a single test case (mirrors LLM output structure)
# ---------------------------------------------------------------------------

class TestCaseItem(BaseModel):
    """One AI-generated QA test case."""
    title: str
    objective: str
    preconditions: str
    test_steps: list[str]
    expected_result: str
    priority: str  # "High" | "Medium" | "Low"


# ---------------------------------------------------------------------------
# GET /selections/{id}/tests
# ---------------------------------------------------------------------------

class TestRunResponse(BaseModel):
    """
    One generation run for a selection.

    A selection can have multiple runs (each call to generate-tests
    creates a new row), so we return a list of them ordered by
    most recent first.
    """
    result_id: int = Field(..., description="Primary key of the TestGenResult row.")
    generated_at: datetime
    model: str = Field(..., description="Gemini model used (e.g. gemini-flash-lite-latest).")
    retry_count: int
    tests: list[TestCaseItem]


class SelectionTestsResponse(BaseModel):
    """Full response for GET /selections/{id}/tests."""
    selection_id: int
    selection_name: str
    version_id: int
    total_runs: int = Field(..., description="Total generation runs for this selection.")
    runs: list[TestRunResponse]


# ---------------------------------------------------------------------------
# GET /nodes/{id}/tests
# ---------------------------------------------------------------------------

class NodeTestRunResponse(BaseModel):
    """
    One generation run that references a given node.

    A node can appear in multiple selections, each of which may have
    multiple generation runs — so we include both identifiers.
    """
    result_id: int
    selection_id: int
    selection_name: str
    generated_at: datetime
    model: str
    tests: list[TestCaseItem]


class NodeTestsResponse(BaseModel):
    """Full response for GET /nodes/{id}/tests."""
    node_id: int
    node_heading: str
    total_runs: int = Field(
        ...,
        description="Total generation runs across all selections containing this node.",
    )
    runs: list[NodeTestRunResponse]


# ---------------------------------------------------------------------------
# Shared: paginated metadata
# ---------------------------------------------------------------------------

class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int
    has_more: bool


# ---------------------------------------------------------------------------
# GET /tests/{id}/status
# ---------------------------------------------------------------------------

class StaleNodeDetail(BaseModel):
    """Details of a node that made the test run stale."""
    node_id: int
    heading: str
    stored_hash: str | None
    current_hash: str | None
    reason: str  # "changed" | "deleted"


class TestStalenessResponse(BaseModel):
    """Response payload for the staleness status check."""
    status: str = Field(..., description="Either 'CURRENT' or 'STALE'.")
    changed_nodes: list[StaleNodeDetail] | None = Field(
        None,
        description="List of nodes that have changed or been deleted since test generation.",
    )
