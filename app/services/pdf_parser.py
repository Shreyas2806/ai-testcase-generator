import logging
from pathlib import Path
from statistics import mode
from typing import Any

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias for a parsed content block
# ---------------------------------------------------------------------------
Block = dict[str, Any]

# Bullet characters and prefixes that indicate a list item
_BULLET_CHARS = {"•", "–", "-", "▪", "◦", "▸", "★", "*", "·"}


def _classify_block_type(
    text: str,
    font_size: float,
    font_flags: int,
    dominant_size: float,
) -> str:
    """
    Classify a text span into one of five content types.

    Classification is adaptive — thresholds are relative to the document's
    dominant (body) font size, not hardcoded pixel values.

    Args:
        text:          The span's text content (stripped).
        font_size:     The span's font size in points.
        font_flags:    PyMuPDF font flags bitmask.
                       Bit 4 (value 16) = bold; Bit 1 (value 2) = italic.
        dominant_size: The most common font size in the document (body text).

    Returns:
        One of: "heading" | "subheading" | "list" | "paragraph" | "unknown"
    """
    if not text:
        return "unknown"

    # -- 1. Size-based classification (check headings first) --
    if dominant_size > 0:
        ratio = font_size / dominant_size
        if ratio >= 1.4:  # Ratio threshold for main headings
            return "heading"
        if ratio >= 1.15: # Ratio threshold for subheadings
            return "subheading"

    # -- 2. Bold text at body size = treat as subheading --
    is_bold = bool(font_flags & 16)
    if is_bold and font_size >= dominant_size:
        return "subheading"

    # -- 3. List detection (lower priority for normal text/lists) --
    # Check first character for bullet symbols
    first_char = text.lstrip()[0] if text.lstrip() else ""
    if first_char in _BULLET_CHARS:
        return "list"

    # Numbered list: "1." / "1)" / "(1)" patterns
    stripped = text.lstrip()
    if len(stripped) > 2:
        prefix = stripped[:3]
        if (
            (prefix[0].isdigit() and prefix[1] in (".", ")"))
            or (prefix[0] == "(" and prefix[1].isdigit())
        ):
            return "list"

    return "paragraph"


def _dominant_font_size(doc: fitz.Document) -> float:
    """
    Determine the most frequently occurring font size across the document.

    This is our proxy for "body text" size and anchors all relative
    classification thresholds.
    """
    sizes: list[int] = []
    for page in doc:
        data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for block in data.get("blocks", []):
            if block.get("type") != 0:  # skip image blocks
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0)
                    if size > 0:
                        # Round to nearest 0.5pt to group near-identical sizes
                        sizes.append(round(size * 2) / 2)

    if not sizes:
        return 11.0  # safe fallback

    try:
        return mode(sizes)
    except Exception:
        return sorted(sizes)[len(sizes) // 2]  # median fallback


class PDFParser:
    """
    Extracts structured content blocks from a PDF file using PyMuPDF.

    Usage:
        parser = PDFParser("path/to/file.pdf")
        parser.load_pdf()
        blocks = parser.extract_blocks()

    Each block in the returned list is a dict with:
        text       : str   — cleaned text content
        page       : int   — 1-based page number
        font_size  : float — size in points
        font_name  : str   — font family name
        bbox       : list  — [x0, y0, x1, y1] bounding box in points
        type       : str   — "heading"|"subheading"|"list"|"paragraph"|"unknown"
    """

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)
        self._doc: fitz.Document | None = None
        self._dominant_size: float = 11.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_pdf(self) -> None:
        """
        Open the PDF file and compute the dominant font size.

        Raises:
            FileNotFoundError: if the file does not exist.
            fitz.FileDataError: if the file is not a valid PDF.
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.file_path}")

        logger.info("Loading PDF: %s", self.file_path)
        self._doc = fitz.open(str(self.file_path))
        self._dominant_size = _dominant_font_size(self._doc)
        logger.info(
            "Loaded %d page(s). Dominant font size: %.1fpt",
            len(self._doc),
            self._dominant_size,
        )

    def extract_blocks(self) -> list[Block]:
        """
        Extract all visible text blocks and tables from the loaded PDF.

        Each PyMuPDF "span" (a run of text with uniform font/size) or detected
        table becomes one output block. Blank spans and spans that fall inside
        tables are skipped.

        Returns:
            A list of block dicts ordered by page and vertical reading order.

        Raises:
            RuntimeError: if load_pdf() has not been called first.
        """
        if self._doc is None:
            raise RuntimeError("Call load_pdf() before extract_blocks().")

        results: list[Block] = []

        for page_index, page in enumerate(self._doc):
            page_number = page_index + 1  # convert to 1-based

            # -- 1. Identify and extract tables on this page --
            try:
                tables = page.find_tables()
            except Exception as exc:
                logger.warning("Table detection failed on page %d: %s", page_number, exc)
                tables = None

            page_tables = []
            table_bboxes = []
            if tables and tables.tables:
                for table in tables.tables:
                    try:
                        md_text = table.to_markdown()
                        if md_text and md_text.strip():
                            bbox = [round(v, 2) for v in table.bbox]
                            page_tables.append({
                                "text": md_text.strip(),
                                "page": page_number,
                                "font_size": self._dominant_size,
                                "font_name": "Table",
                                "bbox": bbox,
                                "type": "paragraph",  # treat table as a body paragraph in the tree
                            })
                            table_bboxes.append(table.bbox)
                    except Exception as exc:
                        logger.warning("Failed to convert table to markdown on page %d: %s", page_number, exc)

            # Helper to check if a span's center lies within any detected table boundary
            def _is_inside_table(span_bbox: list[float]) -> bool:
                if not table_bboxes:
                    return False
                cx = (span_bbox[0] + span_bbox[2]) / 2
                cy = (span_bbox[1] + span_bbox[3]) / 2
                for tx0, ty0, tx1, ty1 in table_bboxes:
                    if (tx0 <= cx <= tx1) and (ty0 <= cy <= ty1):
                        return True
                return False

            # -- 2. Extract standard text spans --
            # get_text("dict") returns the full block/line/span tree.
            # flags= preserves whitespace so we don't collapse indentation.
            data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            page_text_blocks = []

            for block in data.get("blocks", []):
                # block type 1 = image — skip, we only extract text
                if block.get("type") != 0:
                    continue

                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue  # skip blank spans

                        bbox = [round(v, 2) for v in span.get("bbox", [])]

                        # Skip text that belongs to a table, since it's already extracted as structured MD
                        if _is_inside_table(bbox):
                            continue

                        font_size = round(span.get("size", 0), 2)
                        font_name = span.get("font", "unknown")
                        font_flags = span.get("flags", 0)

                        block_type = _classify_block_type(
                            text=text,
                            font_size=font_size,
                            font_flags=font_flags,
                            dominant_size=self._dominant_size,
                        )

                        page_text_blocks.append(
                            {
                                "text": text,
                                "page": page_number,
                                "font_size": font_size,
                                "font_name": font_name,
                                "bbox": bbox,
                                "type": block_type,
                            }
                        )

            # -- 3. Merge text and table blocks, and sort in reading order --
            combined_blocks = page_text_blocks + page_tables
            combined_blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))

            results.extend(combined_blocks)

        logger.info("Extracted %d block(s) from %s", len(results), self.file_path.name)
        return results

    def close(self) -> None:
        """Release the PDF file handle."""
        if self._doc is not None:
            self._doc.close()
            self._doc = None

    # Allow use as a context manager: `with PDFParser(...) as p:`
    def __enter__(self) -> "PDFParser":
        self.load_pdf()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        pages = len(self._doc) if self._doc else "not loaded"
        return f"<PDFParser file={self.file_path.name!r} pages={pages}>"
