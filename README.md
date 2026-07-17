# AI Test Automation Platform

This is a backend service built with **FastAPI**, **SQLAlchemy**, and the **Google genai** SDK. It takes PDF manuals or specifications, parses them into structured hierarchies, manages document versions, lets you select specific parts of a document, and uses Google Gemini to generate structured QA test cases. 

It also keeps track of whether your generated tests are out of date (stale) when someone updates the source text in the document.

---

## What It Can Do

- **Smart PDF Ingestion**: Extracts text using PyMuPDF (fitz) and uses font size differences to classify what's a heading, list, or normal paragraph.
- **Tree Hierarchy**: Turns the flat list of parsed text blocks into a clean parent-child tree structure.
- **Versioning & Diffing**: Lets you upload new versions of a document. It matches sections across versions using their heading paths and checks content hashes to figure out what was added, changed, or deleted.
- **Selections**: Lets you group specific nodes/sections together into a named selection.
- **Gemini Test Generation**: Generates exactly 5 structured QA test cases for any selection. It has a built-in 3-attempt retry loop that fixes malformed JSON output from the LLM automatically.
- **Stale Detection**: Saves the content hash of nodes when tests are generated. If a node is updated or deleted later, it flags the test suite as stale and tells you exactly what changed.

---

## How It's Organized

The app uses a standard layout to keep the code clean and easy to navigate:

```
project/
├── app/
│   ├── api/            # API endpoints (routing, transactions, response mapping)
│   ├── core/           # Configuration settings and logging setup
│   ├── database/       # Database engine and session setup
│   ├── models/         # SQLAlchemy database models
│   ├── schemas/        # Pydantic validation schemas
│   ├── services/       # All business logic (PDF parsing, Gemini integration, diffs)
│   └── tests/          # Pytest unit tests
├── pytest.ini          # Pytest config
├── requirements.txt    # Python dependencies
└── .env                # App secrets (API keys, DB connection strings)
```

---

## Getting Started

### Prerequisites
- Python 3.10+
- A Gemini API key (you can grab a free one from [Google AI Studio](https://aistudio.google.com/app/apikey))

### 1. Set up a virtual environment
```bash
python -m venv venv

# Activate on Windows (PowerShell)
venv\Scripts\Activate.ps1

# Activate on Linux / macOS
source venv/bin/activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure the environment
Create a `.env` file in the root of the project:
```env
DATABASE_URL="sqlite:///./test_automation.db"
GEMINI_API_KEY="your-actual-api-key"
GEMINI_MODEL="models/gemini-flash-lite-latest"
```

### 4. Run the app
Start the local server using Uvicorn:
```bash
uvicorn app.main:app --reload
```
Open up your browser and head to:
- **Swagger UI**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (best way to interact with the API)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

*Note: The SQLite database initializes itself automatically when the server starts up, so you don't need to run any SQL scripts to get started.*

---

## API Endpoints at a Glance

### Document & Versioning
- `POST /documents/upload` - Upload a PDF. Pass a `document_id` query parameter to save it as a new version of an existing document.
- `GET /documents` - List all documents.
- `GET /documents/nodes/{node_id}` - Fetch a specific node and its entire recursive tree of children.
- `GET /documents/search?q=term` - Search headings and body text.
- `POST /documents/versions/{v1_id}/diff/{v2_id}` - Calculate and store the diff between two versions.
- `GET /documents/diff/{node_id}` - Get the diff status of a specific node.

### Selections
- `POST /selections` - Create a selection of node IDs for a specific document version.
- `GET /selections` - List all selections.
- `GET /selections/{id}` - Fetch selection details.
- `DELETE /selections/{id}` - Delete a selection.

### AI & Test Generation
- `POST /selections/{id}/generate-tests` - Send selection text to Gemini and generate test cases.
- `GET /selections/{id}/tests` - List test generation runs for a selection.
- `GET /nodes/{id}/tests` - Find all tests covering a specific node.
- `GET /tests/{id}/status` - Check if a test run is stale relative to current document node hashes.

---

## Re-ingestion & Versioning Walkthrough (v1 -> v2)

Follow these steps to trigger and verify the end-to-end versioning and staleness detection flow:

1. **Ingest Version 1 of the Manual**:
   - Send a `POST /documents/upload` request with your manual PDF file (e.g. `ct200_manual_v1.pdf`).
   - The response will return a `document_id` (e.g. `1`) and version number `1`.

2. **Create a Named Selection**:
   - Pin a group of section nodes to Version 1 by sending a `POST /selections` request:
     ```json
     {
       "version_id": 1,
       "name": "Safety Checks Suite",
       "description": "Critical power and pressure threshold validations.",
       "node_ids": [2, 3, 5]
     }
     ```
   - Note the returned `id` of the selection (e.g. `1`).

3. **Generate AI Test Cases**:
   - Trigger the LLM generation for your selection via `POST /selections/1/generate-tests`.
   - This sends the selected content to Gemini, validates the output against the Pydantic schema, saves the content hashes, and returns exactly 5 structured test cases.
   - Note the returned `result_id` (e.g. `1`) representing this test execution run.

4. **Upload a New Version (v2)**:
   - When a modified manual (e.g. `ct200_manual_v2.pdf`) is published, upload it via `POST /documents/upload?document_id=1`.
   - The API creates a new `Version` (number `2`) under the same document without destroying Version 1.

5. **Compute the Version Difference**:
   - Trigger the version diff by sending a `POST /documents/versions/1/diff/2` request.
   - The service maps sections between v1 and v2 using their heading paths, checks hashes to find new, deleted, or changed text, and generates inline word-level diff summaries.

6. **Check for Stale Test Cases**:
   - Query if your original test run is still accurate against the latest manual by sending a `GET /tests/1/status` request.
   - If any of the selected nodes (`2`, `3`, or `5`) were modified or deleted in v2, it returns status `"STALE"` along with a list of the modified sections and their diff descriptions. Otherwise, it returns `"CURRENT"`.

---

## Running the Tests

To run the automated tests:
```bash
pytest -v
```

---

## Troubleshooting Tips

### Rate limit errors (HTTP 429)
The free tier of the Gemini API can be quite strict. If you get a 429 rate limit error, the service is built to wait and try again up to 3 times. If it still fails, wait a minute before making another request, or try using `models/gemini-flash-lite-latest` which usually has more generous limits.

### Missing modules when running tests
If you see `ModuleNotFoundError: No module named 'app'`, make sure you are running `pytest` from the project root directory and your virtual environment is active. The custom `pytest.ini` is set up to add the project root to your path automatically.
