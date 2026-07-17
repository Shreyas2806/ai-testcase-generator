import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.database import get_db
from app.models.node import Node as DBNode
from app.models.node_diff import NodeDiff
from app.models.version import Version
from app.schemas.document import (
    DiffResponse,
    DocumentSummary,
    NodeResponse,
    SearchResult,
    UploadResponse,
    VersionDiffSummary,
)
from app.services.diff_service import compute_diff, get_node_diff
from app.services.document_storage import DocumentStorageService
from app.services.hierarchy_builder import HierarchyBuilder
from app.services.pdf_parser import PDFParser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_upload_dir() -> Path:
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and parse a PDF document",
    description=(
        "Accepts a PDF file, extracts its text content using PyMuPDF, "
        "builds a structural hierarchy, and persists everything to the database. "
        "Pass `document_id` to add a new version to an existing document "
        "(for versioning/diff workflows). Omit it to create a new document."
    ),
)
async def upload_document(
    file: UploadFile = File(..., description="A valid PDF file."),
    document_id: Optional[int] = Query(
        None,
        description="Existing document ID to attach this upload as a new version.",
    ),
    db: Session = Depends(get_db),
) -> UploadResponse:
    # -- 1. Validate file type --
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only PDF files are accepted.",
        )

    # -- 2. Save to disk --
    upload_dir = _get_upload_dir()
    dest_path = upload_dir / file.filename
    try:
        with dest_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except OSError as exc:
        logger.error("Failed to save uploaded file: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save the uploaded file.",
        )
    finally:
        await file.close()

    logger.info("File saved: %s", dest_path)

    # -- 3. Parse PDF --
    try:
        with PDFParser(dest_path) as parser:
            blocks = parser.extract_blocks()
    except Exception as exc:
        logger.error("PDF parsing failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse PDF: {exc}",
        )

    if not blocks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No extractable text found in this PDF.",
        )

    # -- 4. Build hierarchy --
    roots = HierarchyBuilder(blocks).build_tree()

    # -- 5. Persist --
    service = DocumentStorageService(db)
    try:
        if document_id:
            # Validate the document exists
            from app.models.document import Document
            doc = db.query(Document).filter(Document.id == document_id).first()
            if not doc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document id={document_id} not found.",
                )
        else:
            doc = service.save_document(
                name=Path(file.filename).stem.replace("_", " ").replace("-", " ").title(),
                file_path=str(dest_path),
            )

        version = service.save_version(doc.id)
        service.save_tree(roots, version.id)
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("DB persist failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {exc}",
        )

    logger.info("Upload OK: doc=%d version=%d", doc.id, version.version_number)
    return UploadResponse(
        document_id=doc.id,
        version=version.version_number,
        message=f"'{doc.name}' — version {version.version_number} stored successfully.",
    )


# ---------------------------------------------------------------------------
# GET /documents
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[DocumentSummary],
    summary="List all documents",
)
def list_documents(db: Session = Depends(get_db)) -> list[DocumentSummary]:
    from sqlalchemy import func
    from app.models.document import Document

    rows = (
        db.query(Document.id, Document.name, func.count(Version.id).label("versions"))
        .outerjoin(Version, Version.document_id == Document.id)
        .group_by(Document.id)
        .all()
    )
    return [
        DocumentSummary(id=row.id, name=row.name, versions=row.versions)
        for row in rows
    ]

# ---------------------------------------------------------------------------
# GET /documents/{document_id}/sections
# ---------------------------------------------------------------------------

@router.get(
    "/{document_id}/sections",
    response_model=list[NodeResponse],
    summary="List top-level sections for a document version",
    description=(
        "Retrieves all root nodes (sections with no parent) for the specified "
        "document. If `version` is provided, fetches the root nodes for that specific "
        "version. Otherwise, defaults to the latest version of the document."
    ),
)
def list_top_level_sections(
    document_id: int,
    version: Optional[int] = Query(
        None,
        description="Version number to retrieve. Defaults to the latest version."
    ),
    db: Session = Depends(get_db),
) -> list[NodeResponse]:
    from app.models.document import Document

    # 1. Validate document exists
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document id={document_id} not found."
        )

    # 2. Get version
    if version is not None:
        db_version = (
            db.query(Version)
            .filter(Version.document_id == document_id, Version.version_number == version)
            .first()
        )
        if not db_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version} not found for document id={document_id}."
            )
    else:
        # Default to latest version
        db_version = (
            db.query(Version)
            .filter(Version.document_id == document_id)
            .order_by(Version.version_number.desc())
            .first()
        )
        if not db_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No versions found for document id={document_id}."
            )

    # 3. Fetch top-level nodes (parent_id is Null)
    root_nodes = (
        db.query(DBNode)
        .filter(DBNode.version_id == db_version.id, DBNode.parent_id.is_(None))
        .order_by(DBNode.order_index.asc())
        .all()
    )

    return [_node_to_response(n) for n in root_nodes]


# ---------------------------------------------------------------------------
# GET /nodes/{node_id}
# ---------------------------------------------------------------------------

@router.get(
    "/nodes/{node_id}",
    response_model=NodeResponse,
    summary="Get a node and its full subtree",
)
def get_node(node_id: int, db: Session = Depends(get_db)) -> NodeResponse:
    node = db.query(DBNode).filter(DBNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail=f"Node id={node_id} not found.")
    return _node_to_response(node)


def _node_to_response(node: DBNode) -> NodeResponse:
    """Recursively build NodeResponse from a DBNode."""
    return NodeResponse(
        id=node.id,
        heading=node.heading,
        body=node.content,
        content_hash=node.content_hash,
        node_type=node.node_type,
        page_number=node.page_number,
        order_index=node.order_index,
        children=[_node_to_response(c) for c in node.children],
    )


# ---------------------------------------------------------------------------
# GET /search
# ---------------------------------------------------------------------------

@router.get(
    "/search",
    response_model=list[SearchResult],
    summary="Search nodes by heading or body text",
)
def search_nodes(
    q: str = Query(..., min_length=1, description="Search term"),
    db: Session = Depends(get_db),
) -> list[SearchResult]:
    term = f"%{q.lower()}%"
    matches = (
        db.query(DBNode)
        .filter(
            DBNode.heading.ilike(term) | DBNode.content.ilike(term)
        )
        .limit(50)
        .all()
    )

    results = []
    for node in matches:
        match_in = "heading" if q.lower() in node.heading.lower() else "body"
        results.append(
            SearchResult(
                node_id=node.id,
                heading=node.heading,
                body_preview=(node.content or "")[:200] or None,
                page_number=node.page_number,
                match_in=match_in,
            )
        )
    return results


# ---------------------------------------------------------------------------
# POST /versions/{v1_id}/diff/{v2_id}   — trigger diff computation
# ---------------------------------------------------------------------------

@router.post(
    "/versions/{version1_id}/diff/{version2_id}",
    response_model=VersionDiffSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Compute and store diff between two versions",
    tags=["Versioning"],
)
def run_diff(
    version1_id: int,
    version2_id: int,
    db: Session = Depends(get_db),
) -> VersionDiffSummary:
    # Validate both versions exist
    for vid in (version1_id, version2_id):
        if not db.query(Version).filter(Version.id == vid).first():
            raise HTTPException(status_code=404, detail=f"Version id={vid} not found.")

    try:
        diffs = compute_diff(version1_id, version2_id, db)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Diff computation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Diff failed: {exc}")

    counts = {"new": 0, "changed": 0, "unchanged": 0, "deleted": 0}
    for d in diffs:
        counts[d.status] += 1

    return VersionDiffSummary(
        version1_id=version1_id,
        version2_id=version2_id,
        **counts,
        total=len(diffs),
    )


# ---------------------------------------------------------------------------
# GET /diff/{node_id}   — Phase 8
# ---------------------------------------------------------------------------

@router.get(
    "/diff/{node_id}",
    response_model=DiffResponse,
    summary="Get diff result for a specific node",
    tags=["Versioning"],
)
def get_diff(node_id: int, db: Session = Depends(get_db)) -> DiffResponse:
    """
    Returns the diff status and summary for a node.

    Works for both v1 nodes (deleted) and v2 nodes (new/changed/unchanged).
    If no diff has been computed yet, returns 404.
    """
    diff = get_node_diff(node_id, db)
    if not diff:
        raise HTTPException(
            status_code=404,
            detail=f"No diff found for node id={node_id}. Run a diff first.",
        )

    return DiffResponse(
        node_id=node_id,
        changed=diff.status in ("changed", "new", "deleted"),
        status=diff.status,
        summary=diff.diff_summary or "",
        node_path=diff.node_path,
        version1_id=diff.version1_id,
        version2_id=diff.version2_id,
        v1_node_id=diff.v1_node_id,
        v2_node_id=diff.v2_node_id,
    )
