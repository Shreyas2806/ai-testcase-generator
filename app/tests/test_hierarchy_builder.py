"""
Unit tests for app.services.hierarchy_builder.HierarchyBuilder.
"""

from app.services.hierarchy_builder import HierarchyBuilder, Node


# ---------------------------------------------------------------------------
# Test 1: Duplicate Headings
# ---------------------------------------------------------------------------

def test_duplicate_headings():
    """
    Test Purpose:
        Verify that HierarchyBuilder handles sections with identical names correctly,
        creating distinct nodes and mapping the correct body paragraphs to each section.

    Input:
        A list of blocks representing two sections with duplicate headings.

    Expected Output:
        Two distinct top-level Node objects with matching names but different bodies.
    """
    blocks = [
        {
            "text": "1. Introduction",
            "page": 1,
            "font_size": 20.0,
            "font_name": "Helvetica-Bold",
            "bbox": [50.0, 100.0, 200.0, 120.0],
            "type": "heading",
        },
        {
            "text": "This is the first introduction paragraph.",
            "page": 1,
            "font_size": 10.0,
            "font_name": "Helvetica",
            "bbox": [50.0, 130.0, 400.0, 150.0],
            "type": "paragraph",
        },
        {
            "text": "2. Introduction",
            "page": 2,
            "font_size": 20.0,
            "font_name": "Helvetica-Bold",
            "bbox": [50.0, 100.0, 200.0, 120.0],
            "type": "heading",
        },
        {
            "text": "This is the second introduction paragraph.",
            "page": 2,
            "font_size": 10.0,
            "font_name": "Helvetica",
            "bbox": [50.0, 130.0, 400.0, 150.0],
            "type": "paragraph",
        },
    ]

    builder = HierarchyBuilder(blocks)
    roots = builder.build_tree()

    assert len(roots) == 2
    
    # First section verification
    assert roots[0].heading == "Introduction"
    assert roots[0].body == "This is the first introduction paragraph."
    assert roots[0].level == 1

    # Second section verification
    assert roots[1].heading == "Introduction"
    assert roots[1].body == "This is the second introduction paragraph."
    assert roots[1].level == 1


# ---------------------------------------------------------------------------
# Test 2: Nested Bullet Lists
# ---------------------------------------------------------------------------

def test_nested_bullet_lists():
    """
    Test Purpose:
        Verify that HierarchyBuilder appends bullet list elements (including nested lists)
        to the body content of the nearest active parent node in the correct reading order.

    Input:
        A heading followed by a paragraph and bullet items categorized as 'list' type.

    Expected Output:
        One root node where the body contains all list items and paragraphs,
        joined by newlines.
    """
    blocks = [
        {
            "text": "Features list",
            "page": 1,
            "font_size": 18.0,
            "type": "heading",
        },
        {
            "text": "The platform offers:",
            "page": 1,
            "font_size": 10.0,
            "type": "paragraph",
        },
        {
            "text": "- PDF Parsing",
            "page": 1,
            "font_size": 10.0,
            "type": "list",
        },
        {
            "text": "  * Speed optimization",
            "page": 1,
            "font_size": 10.0,
            "type": "list",
        },
        {
            "text": "  * High accuracy",
            "page": 1,
            "font_size": 10.0,
            "type": "list",
        },
    ]

    builder = HierarchyBuilder(blocks)
    roots = builder.build_tree()

    assert len(roots) == 1
    node = roots[0]
    assert node.heading == "Features list"
    
    # Expected body text splits lines by newlines
    expected_body = (
        "The platform offers:\n"
        "- PDF Parsing\n"
        "* Speed optimization\n"
        "* High accuracy"
    )
    assert node.body == expected_body


# ---------------------------------------------------------------------------
# Test 3: Heading Split Across Multiple Lines
# ---------------------------------------------------------------------------

def test_split_headings():
    """
    Test Purpose:
        Verify that HierarchyBuilder treats consecutive heading blocks of the same level
        as separate sibling nodes (and does not auto-merge them). This confirms the 
        expected structural tree behavior for unmerged PDF lines.

    Input:
        Two consecutive heading blocks with the same font size (level 1).

    Expected Output:
        Two separate sibling Node objects under the root (virtual parent).
    """
    blocks = [
        {
            "text": "1. Introduction to the",
            "page": 1,
            "font_size": 20.0,
            "type": "heading",
        },
        {
            "text": "AI Test Automation System",
            "page": 1,
            "font_size": 20.0,
            "type": "heading",
        },
    ]

    builder = HierarchyBuilder(blocks)
    roots = builder.build_tree()

    # Verify they are created as separate siblings
    assert len(roots) == 2
    assert roots[0].heading == "Introduction to the"
    assert roots[0].level == 1
    assert roots[1].heading == "AI Test Automation System"
    assert roots[1].level == 1


# ---------------------------------------------------------------------------
# Test 4: Multi-level Nesting
# ---------------------------------------------------------------------------

def test_multi_level_nesting():
    """
    Test Purpose:
        Verify that HierarchyBuilder assigns correct parent-child relationships and levels 
        when parsing nested sections spanning multiple levels (e.g. levels 1, 2, and 3).

    Input:
        A list of headings mapping to 3 distinct levels (L1, L2, L3, and another L2).

    Expected Output:
        A tree showing:
          Root
           L1 Node
             L2 Node A
               L3 Node
             L2 Node B
    """
    blocks = [
        {
            "text": "1. Main Title",
            "page": 1,
            "font_size": 24.0,
            "type": "heading",
        },
        {
            "text": "1.1 Sub-section A",
            "page": 1,
            "font_size": 20.0,
            "type": "heading",
        },
        {
            "text": "1.1.1 Nested detail",
            "page": 1,
            "font_size": 14.0,
            "type": "heading",
        },
        {
            "text": "1.2 Sub-section B",
            "page": 1,
            "font_size": 20.0,
            "type": "heading",
        },
    ]

    builder = HierarchyBuilder(blocks)
    roots = builder.build_tree()

    # 1. Top level
    assert len(roots) == 1
    root_node = roots[0]
    assert root_node.heading == "Main Title"
    assert root_node.level == 1
    assert len(root_node.children) == 2

    # 2. Level 2
    l2_node_a = root_node.children[0]
    l2_node_b = root_node.children[1]
    
    assert l2_node_a.heading == "Sub-section A"
    assert l2_node_a.level == 2
    assert len(l2_node_a.children) == 1

    assert l2_node_b.heading == "Sub-section B"
    assert l2_node_b.level == 2
    assert len(l2_node_b.children) == 0

    # 3. Level 3
    l3_node = l2_node_a.children[0]
    assert l3_node.heading == "Nested detail"
    assert l3_node.level == 3
    assert len(l3_node.children) == 0
