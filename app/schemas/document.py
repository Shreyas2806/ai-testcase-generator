from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    """Response returned after a successful PDF upload and parse."""
    document_id: int = Field(..., description="Database ID of the created Document.")
    version: int = Field(..., description="Version number assigned (1-based).")
    message: str = Field(..., description="Human-readable status message.")


# ---------------------------------------------------------------------------
# GET /documents
# ---------------------------------------------------------------------------

class DocumentSummary(BaseModel):
    """Lightweight document listing item."""
    id: int = Field(..., description="Document primary key.")
    name: str = Field(..., description="Document title.")
    versions: int = Field(..., description="Number of versions stored.")

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# GET /nodes/{id}
# ---------------------------------------------------------------------------

class NodeResponse(BaseModel):
    """Full node detail including recursive children."""
    id: int
    heading: str
    body: str | None = Field(None, description="Body content under this heading.")
    content_hash: str | None = Field(None, description="SHA-256 of body content.")
    node_type: str
    page_number: int | None
    order_index: int
    children: list["NodeResponse"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# Required for self-referential Pydantic model to resolve forward reference
NodeResponse.model_rebuild()


# ---------------------------------------------------------------------------
# GET /search
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    """A single search hit."""
    node_id: int = Field(..., description="ID of the matching node.")
    heading: str
    body_preview: str | None = Field(
        None, description="First 200 chars of body content."
    )
    page_number: int | None
    match_in: str = Field(
        ..., description="Where the match was found: 'heading' or 'body'."
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# GET /diff/{node_id}
# ---------------------------------------------------------------------------

class DiffResponse(BaseModel):
    """Diff result for a single node compared across two versions."""
    node_id: int = Field(..., description="The node ID that was queried.")
    changed: bool = Field(..., description="True if the node's content changed.")
    status: str = Field(
        ...,
        description="One of: 'unchanged' | 'changed' | 'new' | 'deleted'.",
    )
    summary: str = Field(..., description="Human-readable description of the change.")
    node_path: str = Field(..., description="Heading path used to match this node.")
    version1_id: int
    version2_id: int
    v1_node_id: int | None = None
    v2_node_id: int | None = None


# ---------------------------------------------------------------------------
# Version diff overview
# ---------------------------------------------------------------------------

class VersionDiffSummary(BaseModel):
    """Summary of all diffs between two versions."""
    version1_id: int
    version2_id: int
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    deleted: int = 0
    total: int = 0
