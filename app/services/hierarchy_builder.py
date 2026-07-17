"""
Hierarchy Builder: converts a flat list of PDF-extracted blocks into a tree.

The tree represents the document's logical structure — sections, subsections,
and their body content — inferred from font sizes, block types, and page order.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias — matches the output dict from PDFParser.extract_blocks()
# ---------------------------------------------------------------------------
Block = dict[str, Any]

# Block types that indicate a heading-level element
_HEADING_TYPES = {"heading", "subheading"}

# Strip leading numbering like "1.", "1.1", "2.3.4", "(1)" from heading text
_NUMBERING_RE = re.compile(r"^[\(\s]*[\d]+(?:[.\d]*)[\)\.\s]+")


# ---------------------------------------------------------------------------
# Node — the fundamental unit of the tree
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """
    A single node in the document hierarchy tree.

    Attributes:
        heading   : The heading or title text of this node.
        body      : Accumulated body content (paragraphs, lists) under this heading.
        level     : Hierarchy depth. 1 = top-level, 2 = child, 3 = grandchild, etc.
        page      : Page number where this node's heading appears.
        font_size : Font size of the heading span (used for level detection).
        block_type: Original block type from the parser ("heading", "subheading", etc.)
        children  : Ordered list of child Nodes.
        parent    : Reference to the parent Node (None for root nodes).
    """

    heading: str
    body: str = ""
    level: int = 1
    page: int = 1
    font_size: float = 0.0
    block_type: str = "heading"
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = field(default=None, repr=False)  # excluded from repr

    def add_body(self, text: str) -> None:
        """Append a line of body text, separated by a newline."""
        self.body = (self.body + "\n" + text).strip()

    def add_child(self, child: "Node") -> None:
        """Attach a child node and set its parent back-reference."""
        child.parent = self
        self.children.append(child)

    def __repr__(self) -> str:
        preview = self.heading[:40] + "..." if len(self.heading) > 40 else self.heading
        return (
            f"Node(level={self.level}, page={self.page}, "
            f"children={len(self.children)}, heading={preview!r})"
        )


# ---------------------------------------------------------------------------
# Virtual root — holds all top-level nodes as children
# ---------------------------------------------------------------------------

def _make_root() -> Node:
    """Create the invisible root node that owns all level-1 sections."""
    return Node(heading="__root__", level=0, page=0, font_size=0.0)


# ---------------------------------------------------------------------------
# HierarchyBuilder
# ---------------------------------------------------------------------------

class HierarchyBuilder:
    """
    Converts a flat list of PDFParser blocks into a nested Node tree.

    Usage:
        builder = HierarchyBuilder(blocks)
        roots = builder.build_tree()   # returns list of top-level Node objects

    Algorithm:
        1. Collect all unique heading font sizes.
        2. Sort descending → assign level 1, 2, 3... (largest = highest).
        3. Walk blocks in order; use a stack to track the current ancestry path.
        4. Each heading block: determine level → pop stack to find parent → attach.
        5. Each body block: append text to the current (top-of-stack) node.
    """

    def __init__(self, blocks: list[Block]) -> None:
        self._blocks = blocks
        self._level_map: dict[float, int] = {}  # font_size → hierarchy level
        self._root: Node = _make_root()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_tree(self) -> list[Node]:
        """
        Build and return the list of top-level (level-1) nodes.

        Returns an empty list if no heading blocks are found.
        """
        if not self._blocks:
            logger.warning("HierarchyBuilder received an empty block list.")
            return []

        self._level_map = self._build_level_map()
        logger.info("Heading level map: %s", self._level_map)

        self._attach_children()

        roots = self._root.children
        logger.info(
            "Tree built: %d top-level section(s), %d total node(s).",
            len(roots),
            self._count_nodes(self._root) - 1,  # subtract the virtual root
        )
        return roots

    # ------------------------------------------------------------------
    # Step 1: Level map
    # ------------------------------------------------------------------

    def detect_heading_level(self, font_size: float) -> int:
        """
        Return the hierarchy level (1-based) for a given font size.

        Raises KeyError if font_size is not in the level map.
        """
        return self._level_map[font_size]

    def _build_level_map(self) -> dict[float, int]:
        """
        Map each unique heading font size to a hierarchy level.

        Collects font sizes from all heading/subheading blocks, sorts them
        descending, and assigns level 1 to the largest, 2 to the next, etc.

        Example:
            font sizes in doc : {24.0, 16.0, 13.0}
            → level map       : {24.0: 1, 16.0: 2, 13.0: 3}
        """
        heading_sizes: set[float] = set()
        for block in self._blocks:
            if block.get("type") in _HEADING_TYPES:
                size = block.get("font_size", 0.0)
                if size > 0:
                    heading_sizes.add(size)

        # Sort largest first → highest in hierarchy
        sorted_sizes = sorted(heading_sizes, reverse=True)
        return {size: level for level, size in enumerate(sorted_sizes, start=1)}

    # ------------------------------------------------------------------
    # Step 2: Tree construction using a stack
    # ------------------------------------------------------------------

    def _attach_children(self) -> None:
        """
        Walk all blocks and build the tree using a parent-tracking stack.

        Stack invariant: stack[-1] is always the node that should receive
        the next body text or the parent of the next same/lower level node.
        """
        # Stack holds (level, Node). Start with the virtual root at level 0.
        stack: list[tuple[int, Node]] = [(0, self._root)]

        for block in self._blocks:
            block_type = block.get("type", "unknown")
            text = block.get("text", "").strip()
            if not text:
                continue

            if block_type in _HEADING_TYPES and block.get("font_size", 0) in self._level_map:
                # -- This block is a heading → create a new Node --
                font_size = block["font_size"]
                level = self._level_map[font_size]
                clean_heading = _strip_numbering(text)

                node = Node(
                    heading=clean_heading,
                    level=level,
                    page=block.get("page", 1),
                    font_size=font_size,
                    block_type=block_type,
                )

                # Pop the stack until we find a node whose level is strictly
                # less than the new node's level — that's the parent.
                while len(stack) > 1 and stack[-1][0] >= level:
                    stack.pop()

                parent_node = stack[-1][1]
                parent_node.add_child(node)

                # Push the new node — it may receive children or body text next
                stack.append((level, node))

            else:
                # -- Body content (paragraph, list, unknown) --
                # Append to the current heading node (top of stack),
                # or to root if no heading has been seen yet.
                current_node = stack[-1][1]
                if current_node is not self._root:
                    current_node.add_body(text)
                # Orphaned body text before any heading is silently skipped.

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _count_nodes(node: Node) -> int:
        """Recursively count all nodes including the given node."""
        return 1 + sum(HierarchyBuilder._count_nodes(c) for c in node.children)


# ---------------------------------------------------------------------------
# Pretty-printer (for debugging and testing)
# ---------------------------------------------------------------------------

def pretty_print(nodes: list[Node], indent: int = 0) -> None:
    """
    Recursively print the tree with indentation reflecting depth.

    Example output:
        [L1] Introduction  (p.1, 24.0pt)
             Body: This document describes...
          [L2] Purpose  (p.1, 16.0pt)
          [L2] Features  (p.2, 16.0pt)
               Body: The platform provides...
    """
    prefix = "   " * indent
    for node in nodes:
        connector = "|-- " if indent > 0 else ""
        print(f"{prefix}{connector}[L{node.level}] {node.heading}  "
              f"(p.{node.page}, {node.font_size}pt)")
        if node.body:
            body_preview = node.body[:120].replace("\n", " / ")
            print(f"{prefix}    body: {body_preview}")
        if node.children:
            pretty_print(node.children, indent + 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_numbering(text: str) -> str:
    """
    Remove leading section numbers from heading text.

    '1.2 Introduction' → 'Introduction'
    '3.   Overview'    → 'Overview'
    'Introduction'     → 'Introduction'  (unchanged)
    """
    return _NUMBERING_RE.sub("", text).strip() or text.strip()
