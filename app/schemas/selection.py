from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# POST /selections
# ---------------------------------------------------------------------------

class SelectionCreate(BaseModel):
    """Input payload for creating a new Selection."""
    version_id: int = Field(..., description="The Version ID this selection is tied to.")
    name: str = Field(..., min_length=1, max_length=255, description="Name of the selection (e.g. 'Safety Rules').")
    node_ids: list[int] = Field(..., description="List of node IDs to include in the selection.")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class SelectionNodeResponse(BaseModel):
    """Lightweight representation of a Node inside a Selection."""
    node_id: int
    heading: str
    node_type: str

    model_config = {"from_attributes": True}


class SelectionResponse(BaseModel):
    """Full representation of a Selection."""
    id: int
    version_id: int
    name: str
    description: str | None = None
    nodes: list[SelectionNodeResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# POST /selections/{id}/generate-tests
# ---------------------------------------------------------------------------

class TestCaseItemResponse(BaseModel):
    """A single AI-generated QA test case."""
    title: str
    objective: str
    preconditions: str
    test_steps: list[str]
    expected_result: str
    priority: str


class TestGenResponse(BaseModel):
    """Response returned after a successful AI test generation run."""
    result_id: int = Field(..., description="ID of the stored TestGenResult row.")
    selection_id: int
    model_name: str
    retry_count: int = Field(..., description="How many Gemini retries were needed (0 = first attempt succeeded).")
    test_cases: list[TestCaseItemResponse]
