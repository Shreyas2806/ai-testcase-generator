from unittest.mock import MagicMock, patch
from app.services.pdf_parser import PDFParser

def test_pdf_parser_table_extraction():
    """
    Test that PDFParser identifies tables via page.find_tables(),
    converts them to Markdown, and filters out standard text spans 
    that fall inside the table's bounding box.
    """
    # 1. Mock page and document
    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_doc.__iter__.return_value = [mock_page]
    mock_doc.__len__.return_value = 1

    # 2. Mock a table inside the page
    mock_table = MagicMock()
    mock_table.bbox = (50.0, 150.0, 300.0, 250.0)  # table bbox: x0, y0, x1, y1
    mock_table.to_markdown.return_value = (
        "| Parameter | Value |\n| --- | --- |\n| Cuff Pressure | 150 |\n"
    )

    mock_tables_obj = MagicMock()
    mock_tables_obj.tables = [mock_table]
    mock_page.find_tables.return_value = mock_tables_obj

    # 3. Mock standard text spans on the page
    # Span 1: Heading (outside table)
    # Span 2: Paragraph (inside table - should be skipped)
    # Span 3: Paragraph (outside table)
    mock_page.get_text.return_value = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "spans": [
                            {
                                "text": "Device Specifications",
                                "size": 24.0,
                                "font": "Helvetica-Bold",
                                "flags": 16,
                                "bbox": (50.0, 50.0, 250.0, 70.0),
                            }
                        ]
                    },
                    {
                        "spans": [
                            {
                                "text": "Cuff Pressure",
                                "size": 10.0,
                                "font": "Helvetica",
                                "flags": 0,
                                "bbox": (60.0, 160.0, 120.0, 175.0),  # inside table!
                            }
                        ]
                    },
                    {
                        "spans": [
                            {
                                "text": "This is a safety limit.",
                                "size": 10.0,
                                "font": "Helvetica",
                                "flags": 0,
                                "bbox": (50.0, 300.0, 300.0, 315.0),  # outside table!
                            }
                        ]
                    }
                ]
            }
        ]
    }

    # 4. Patch fitz.open and _dominant_font_size to return expected test values
    with patch("fitz.open", return_value=mock_doc), \
         patch("app.services.pdf_parser._dominant_font_size", return_value=10.0):
        
        parser = PDFParser("requirements.txt")
        parser.load_pdf()
        blocks = parser.extract_blocks()

        # 5. Assertions
        # Expecting exactly 3 blocks: Heading, Table (as paragraph), and Paragraph
        assert len(blocks) == 3

        # Heading block
        assert blocks[0]["text"] == "Device Specifications"
        assert blocks[0]["type"] == "heading"

        # Table block (should be inserted in vertical position order y0=150.0)
        assert blocks[1]["type"] == "paragraph"
        assert "| Parameter | Value |" in blocks[1]["text"]
        assert "Cuff Pressure" in blocks[1]["text"]
        assert blocks[1]["bbox"] == [50.0, 150.0, 300.0, 250.0]

        # Paragraph block (vertical position y0=300.0)
        assert blocks[2]["text"] == "This is a safety limit."
        assert blocks[2]["type"] == "paragraph"
        
        # Verify the raw text span that was inside the table boundary is skipped
        raw_texts = [b["text"] for b in blocks]
        assert "Cuff Pressure" not in raw_texts  # it is only in the markdown table, not separate span
