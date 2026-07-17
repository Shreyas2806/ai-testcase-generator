# Approach Document: CardioTrack CT-200 AI Test Automation Backend

This document details the architectural decisions, design patterns, trade-offs, and engineering processes implemented for the CardioTrack CT-200 Home Blood Pressure Monitor Test Automation platform.

---

## 1. OCR & Document Parsing Approach

### Selected Tool: PyMuPDF (fitz)
For text extraction and structure detection, we selected **PyMuPDF**.
- **Why**: PyMuPDF provides pixel-accurate layout coordinates (`bbox`), exact font names, font flags (bold/italic detection), and font sizes.
- **Why not OCR-first (like Tesseract)**: The CT-200 Manual is a digital PDF containing clean vector text. Performing OCR would introduce unnecessary noise (character misrecognition) and is computationally expensive.
- **Why not PyPDF/PdfReader**: These libraries extract flat text strings but discard font properties (sizes, weights) which are crucial for reconstructing a hierarchy.

### Classification Strategy
Instead of hardcoding font sizes (which breaks if document styling changes), we use an **adaptive font profiling** approach:
1. The parser scans the entire document first and computes the **dominant font size** (the mathematical mode). This represents the body text size (typically 10pt–11pt).
2. All block-type classifications are calculated relative to this baseline:
   - **List Items**: Handled with high priority by checking for bullet characters (`•`, `-`, `▪`, etc.) or numerical list prefixes (`1.`, `a.`, etc.).
   - **Headings**: Spans with a size ratio $\ge 1.5$ relative to the dominant size.
   - **Subheadings**: Spans with a size ratio $\ge 1.2$, or bold spans with a size $\ge$ the dominant size.
   - **Paragraphs**: Standard text spans at or below the dominant size.

### Table Extraction & Reading Order
To preserve tabular data and specifications:
1. We query PyMuPDF's table finder (`page.find_tables()`) for each page.
2. For each detected table, we extract its structural layout and convert it to clean Markdown format using `table.to_markdown()`.
3. We check all text spans against the table bounding boxes (`bbox`). Spans whose centers lie inside a table boundary are discarded, preventing the table content from being extracted twice as disjoint text.
4. We merge the structured table blocks (represented as `"type": "paragraph"`) with the standard text blocks and sort them by vertical coordinates (`y0`, then `x0`) to insert the table into the exact reading order of the document.

---

## 2. Hierarchy Reconstruction Strategy

### The Algorithm
The flat block structure extracted by the PDF parser is reconstructed into a hierarchical tree using a **priority stack-based walker**:
1. **Dynamic Level Mapping**: We extract all unique font sizes of blocks classified as `heading` or `subheading`. We sort them in descending order and assign levels (Level 1 is the largest heading font size, Level 2 is the next, etc.).
2. **Stack-Based Assembly**:
   - We initialize a stack with a virtual `__root__` node at Level 0.
   - As we iterate through the blocks:
     - If the block is a heading of Level $L$: we pop elements off the stack until the top element's level is $< L$. The top node becomes the parent. The new node is attached to it and pushed onto the stack.
     - If the block is a paragraph or list item: we append the text to the `body` of the current node at the top of the stack.
3. **Numbering Cleanup**: We strip prefix numbering (e.g. `1.1.2`, `(a)`) from node headings during tree assembly. This ensures headings match semantically across document versions even if numbering structures are adjusted.

---

## 3. Version Matching Strategy & Failure Modes

We chose a **Normalized Heading Path** strategy for version matching.
- **Algorithm**: For each node in a version, we build its absolute path from the root (e.g., `introduction > safety information > electrical safety`). We lowercase the path to ensure case-insensitive matching.
- **Why**: It is highly robust to page additions, deletions, and paragraph reordering. If text moves between pages but remains under the same section, it is correctly identified as the same logical node.

### Known Failure Modes
1. **Typo Correction / Heading Renaming**:
   - *Example*: If version 1 has `Satefy Info` and version 2 corrects it to `Safety Info`, the path changes.
   - *Behavior*: The system will treat this as a deletion of `Satefy Info` and a creation of a new section `Safety Info`. Any test cases generated against the old section will be flagged as stale due to node deletion.
2. **Duplicate Paths (Path Collision)**:
   - *Example*: If a document has two separate sections named `Specifications` under the same parent section `Device Setup`.
   - *Behavior*: The path map (`dict[str, DBNode]`) key will collide. One node will overwrite the other in the map, leading to missing diff markers or incorrect diff computations.
3. **Structural Re-parenting**:
   - *Example*: Moving a section `Calibration` from under `Maintenance` to under `Troubleshooting`.
   - *Behavior*: The path changes from `maintenance > calibration` to `troubleshooting > calibration`. It is treated as a deletion and a new insertion.

---

## 4. LLM Prompt Design & Robust Output Validation

### Prompt Structure
We instruct Gemini using role prompting, structural specifications, and output constraints:
1. **Role**: Expert QA Engineer.
2. **Output Format**: Strictly raw JSON conforming to a specific schema containing a `test_cases` array of objects.
3. **Explicit Constraints**: No markdown formatting, no code blocks (avoiding ```json ... ```), and exactly 5 test cases.

### Structured Validation & Retry Loop
To make the system resilient to LLM drift:
1. **Fenced Code Block Cleanup**: We defensively strip markdown code fences using regex before parsing.
2. **Syntax Validation**: We parse using standard `json.loads()`.
3. **Semantic Validation**: We load the parsed dict into a Pydantic model (`TestCaseList`). Pydantic ensures every single required field (`title`, `objective`, `test_steps`, etc.) is present and of the correct type.
4. **Retry Loop**: If JSON parsing or Pydantic validation fails, the system retries up to 3 times. On subsequent retries, it appends a `REMINDER` detailing the exact failure and reinforcing the rules, preserving context for the model.
5. **Duplicate Policy**: If a user submits the same selection twice, the system runs the generator again and appends a new `TestGenResult` to the database. This acts as an audit trail of generations over time, allowing the user to select the preferred generation run.

---

## 5. Staleness & Impact Detection

### How It Works
1. During test case generation, we record a SHA-256 hash of the content of every node in the selection. These are persisted inside `TestGenResult.stored_hashes`.
2. When a user requests the status of a test run via `/tests/{test_run_id}/status`, the service:
   - Fetches the current database state of those nodes.
   - If a node is missing, it is marked as `deleted`.
   - If the current node's content hash does not match the stored hash, it is marked as `changed`.
   - If any nodes are deleted or changed, the run is flagged as `STALE`.

### Limitations
- **Hash Sensitivity**: It treats a one-character typo correction (e.g., adding a comma) exactly the same as a critical parameter change (e.g., altering a safety pressure threshold from 150mmHg to 180mmHg). 
- **No Propagation to Sub-nodes**: If a child node of a selection changes, but that child node was not explicitly selected, the test suite is not marked as stale.

---

## 6. What We'd Do Differently with More Time

1. **Semantic Diffing**: Implement a small local embedding or LLM-based evaluation to classify if a change is *structural* (e.g. pressure threshold changes) or *cosmetic* (formatting/spacing changes), reducing false-positive staleness alerts.
2. **Handling Heading Collisions**: Add a local node sibling order index to the path (e.g. `introduction > overview [0]`, `introduction > overview [1]`) to eliminate path collisions.
3. **Hierarchical Diff Propagation**: Propagate changes up/down the tree, so that updating a parent section flags children-based test cases as stale if their parent context changes.
4. **Automated Reconciliation**: Build a feature to auto-regenerate or draft modifications for stale test cases based on the diff.

---

## 7. Decision Log

### Q1: What's the one part of this system most likely to silently give wrong results without erroring? How would you catch it?
**Answer**: The PDF parser classification. If PyMuPDF extracts text elements out of reading order (e.g. because of multi-column layouts or float boxes), or if minor font size changes go undetected, the builder will mis-classify headings as paragraphs. The code will complete successfully, but sections will be merged or nested under wrong parents. 
*How to catch it*: We would implement validation scripts checking for "parent-child level skips" (e.g., Level 1 directly owning a Level 3 child with no Level 2 parent in between) and output visual hierarchy audits (like HTML maps) during ingestion for QA inspection.

### Q2: Where did you choose simplicity over correctness because of time, and what would break first if this went to production as-is?
**Answer**: The version-matching path strategy. We assume heading paths are unique. In production, a large document with multiple repeating section titles under the same parent (like nested `Item A`, `Item B` under `Details`) would cause key collisions in the path map. This would overwrite diff statuses, causing changes to go un-tracked and resulting in missing staleness detection.

### Q3: Name one input (to your parser, your versioning matcher, or your LLM call) that you did not handle, and what your system does when it sees it?
**Answer**: Embedded figures, drawings, diagrams, and raster images. The parser skips blocks that are not text/tables (e.g. vector diagrams, schematic drawings, page margin borders, or photographs). When it sees them, it silently ignores them. This means key visual information, such as cuff wrapping illustrations or safety indicator drawings, is not extracted, and the LLM will have no awareness of them when generating QA test cases.
