import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.pdf_parser import PDFParser
from app.services.hierarchy_builder import HierarchyBuilder, pretty_print

def main():
    pdf_path = PROJECT_ROOT / "ct200_manual.pdf"
    if not pdf_path.exists():
        print(f"Error: Manual PDF not found at {pdf_path}")
        return

    print("Step 1: Parsing PDF blocks and tables directly from ct200_manual.pdf...")
    with PDFParser(pdf_path) as parser:
        blocks = parser.extract_blocks()

    print(f"Extracted {len(blocks)} blocks (including text spans and markdown tables).")
    
    # Print some extracted blocks to inspect layout sorting and classification
    print("\nFirst 10 Extracted Blocks for Verification:")
    for i, b in enumerate(blocks[:10]):
        print(f"[{i}] Page {b['page']} | Type: {b['type']} | Font: {b['font_size']}pt | Bbox: {b['bbox']}")
        print(f"    Content: {b['text'][:120]}")

    print("\nStep 2: Reconstructing Document Hierarchy Tree...")
    builder = HierarchyBuilder(blocks)
    roots = builder.build_tree()

    print("\nStep 3: Pretty-printing Hierarchy Tree (up to 3 levels deep):")
    pretty_print(roots)

if __name__ == "__main__":
    main()
