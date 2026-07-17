"""
LLM Service — AI-powered QA test case generation using Google Gemini.

Design decisions explained:

PROMPT ENGINEERING
------------------
We use a single detailed prompt that tells Gemini:
  - Its role (expert QA Engineer)
  - STRICT output contract: JSON-only, no markdown, no fences
  - The exact JSON schema it must produce
  - The source content (concatenated node heading + body)
Being explicit about "no markdown" prevents Gemini from wrapping its
answer in ```json...``` fences, which would break json.loads().

JSON VALIDATION
---------------
After receiving the response:
  1. Strip any accidental markdown fences (defensive).
  2. Parse with json.loads() — catches syntax errors.
  3. Validate through Pydantic (TestCaseList) — catches structural errors,
     missing fields, wrong types.
  4. Assert exactly 5 test cases.

RETRY STRATEGY
--------------
We retry up to MAX_RETRIES=3 times. Each retry appends a "REMINDER"
block to reinforce the JSON-only contract. This works better than
sending a fresh prompt because it preserves the failure context.
We use linear back-off (1s, 2s) to avoid hammering the API.

ERROR HANDLING
--------------
Three failure modes handled explicitly:
  - Not configured: missing API key.
  - APIError: Gemini unreachable or quota exceeded.
  - JSONDecodeError / ValidationError: bad JSON structure from Gemini.
"""

import json
import logging
import re
import time

from google import genai
from google.genai import errors as genai_errors
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.selection import Selection
from app.models.test_gen_result import TestGenResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1   # seconds; doubles each retry: 1s -> 2s


# ---------------------------------------------------------------------------
# Pydantic schema for validating Gemini's JSON response
# ---------------------------------------------------------------------------

class TestCaseItem(BaseModel):
    """
    One QA test case.

    Every field is required. Pydantic will raise a ValidationError if
    Gemini omits or renames any field — this triggers a retry.
    """
    title: str
    objective: str
    preconditions: str
    test_steps: list[str]
    expected_result: str
    priority: str   # "High" | "Medium" | "Low"


class TestCaseList(BaseModel):
    """
    Top-level wrapper expected from Gemini:

    {
        "test_cases": [ { ... }, { ... }, ... ]
    }

    Using a named wrapper key (not a bare array) makes the JSON
    self-describing and allows us to add metadata fields later.
    """
    test_cases: list[TestCaseItem]


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(node_texts: list[str]) -> str:
    """
    Build the generation prompt from the list of node content strings.

    Structure:
      1. Role declaration      — who Gemini is acting as
      2. Output contract       — JSON-only, no fences, no prose
      3. Required JSON schema  — exact structure Gemini must follow
      4. Source content        — the document text from the selected nodes
      5. Task instruction      — the final directive
    """
    content_block = "\n\n".join(
        f"[SECTION {i+1}]\n{text}" for i, text in enumerate(node_texts)
    )

    return f"""You are an expert QA Engineer. Your task is to generate exactly 5 QA test cases
based on the provided document content.

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON. No markdown. No code fences. No explanations.
- Your entire response must be parseable by json.loads().
- Do NOT include ```json or ``` anywhere in your response.

REQUIRED JSON SCHEMA:
{{
  "test_cases": [
    {{
      "title": "short descriptive title",
      "objective": "what this test verifies",
      "preconditions": "what must be true before running",
      "test_steps": ["step 1", "step 2", "step 3"],
      "expected_result": "what should happen",
      "priority": "High | Medium | Low"
    }}
  ]
}}

Rules:
- Generate EXACTLY 5 test cases. No more, no less.
- test_steps must be a JSON array of strings, not a single string.
- priority must be exactly one of: High, Medium, Low.
- Base all test cases on the document content below.

DOCUMENT CONTENT:
{content_block}

Generate the 5 QA test cases now:"""


# ---------------------------------------------------------------------------
# Raw response cleanup
# ---------------------------------------------------------------------------

def _strip_markdown_fences(raw: str) -> str:
    """
    Defensively strip any markdown code fences Gemini may have added.

    Even with explicit instructions, Gemini sometimes wraps its output
    in ```json ... ```. This removes those so json.loads() can parse it.
    """
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    return raw.strip()


# ---------------------------------------------------------------------------
# Core generation function
# ---------------------------------------------------------------------------

def generate_test_cases(selection_id: int, db: Session) -> TestGenResult:
    """
    Generate QA test cases for a Selection using Gemini.

    Steps:
        1. Validate API key and Selection existence.
        2. Extract content from all nodes in the selection.
        3. Build prompt and call Gemini (retry loop, max 3 attempts).
        4. Validate response JSON with Pydantic.
        5. Persist result to TestGenResult.
        6. Return the unsaved (flushed) TestGenResult — caller commits.

    Raises:
        HTTPException 400: API key not configured.
        HTTPException 404: Selection not found.
        HTTPException 422: Gemini returned invalid JSON after all retries.
        HTTPException 503: Gemini API unreachable.
    """

    # -- 0. Guard: API key must be set --
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "your-gemini-api-key-here":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "GEMINI_API_KEY is not configured. "
                "Add it to your .env file: GEMINI_API_KEY=your-key-here. "
                "Get a free key at https://aistudio.google.com/app/apikey"
            ),
        )

    # -- 1. Load Selection --
    selection = db.query(Selection).filter(Selection.id == selection_id).first()
    if not selection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selection id={selection_id} not found.",
        )

    # -- 2. Extract node content --
    node_texts: list[str] = []
    node_hashes: dict[str, str] = {}
    for junction in selection.selection_nodes:
        node = junction.node
        parts = [node.heading]
        if node.content:
            parts.append(node.content)
        node_texts.append("\n".join(parts))
        node_hashes[str(node.id)] = node.content_hash or ""

    if not node_texts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Selection id={selection_id} contains no nodes with content.",
        )

    # -- 3. Initialize Gemini client (new google.genai API) --
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # -- 4. Build prompt and enter retry loop --
    base_prompt = _build_prompt(node_texts)
    last_error: str = ""
    last_raw: str = ""

    for attempt in range(1, MAX_RETRIES + 1):
        if attempt == 1:
            prompt = base_prompt
        else:
            # Append a targeted reminder on retries — preserves context
            # and consistently improves compliance without a full re-prompt.
            prompt = (
                base_prompt
                + f"\n\nREMINDER (attempt {attempt}/{MAX_RETRIES}): "
                "Your previous response was NOT valid JSON. "
                "Return ONLY the raw JSON object. No markdown. No backticks."
            )

        logger.info(
            "Calling Gemini [attempt %d/%d] for selection_id=%d",
            attempt, MAX_RETRIES, selection_id,
        )

        try:
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
            )
            raw_text = response.text
            last_raw = raw_text

            logger.debug(
                "Gemini raw response (attempt %d): %.300s", attempt, raw_text
            )

            # 4a. Strip accidental markdown fences
            cleaned = _strip_markdown_fences(raw_text)

            # 4b. Parse JSON
            parsed_dict = json.loads(cleaned)

            # 4c. Validate structure with Pydantic
            validated = TestCaseList(**parsed_dict)

            # 4d. Enforce exactly 5 test cases
            if len(validated.test_cases) != 5:
                raise ValueError(
                    f"Expected exactly 5 test cases, Gemini returned {len(validated.test_cases)}."
                )

            logger.info("Gemini validated successfully on attempt %d.", attempt)

            # -- 5. Persist result --
            result = TestGenResult(
                selection_id=selection_id,
                generated_json=cleaned,
                model_name=settings.GEMINI_MODEL,
                retry_count=attempt - 1,  # 0 = succeeded on first attempt
                stored_hashes=node_hashes,
            )
            db.add(result)
            db.flush()  # populate result.id without committing

            return result

        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = str(exc)
            logger.warning(
                "Gemini JSON validation failed on attempt %d: %s", attempt, last_error
            )
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY_SECONDS * attempt
                logger.info("Retrying in %ds...", delay)
                time.sleep(delay)

        except genai_errors.ClientError as exc:
            # 429 = quota/rate-limit -> wait and retry
            # Other 4xx/5xx -> fail immediately
            if exc.status_code == 429:
                wait = RETRY_DELAY_SECONDS * attempt * 15  # 15s, 30s, 45s
                logger.warning(
                    "Gemini rate-limited (429) on attempt %d. Waiting %ds before retry...",
                    attempt, wait,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(wait)
                    last_error = f"Rate limited: {exc}"
                    continue
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        "Gemini API quota exceeded. "
                        "Please wait a minute and try again, or upgrade your API plan."
                    ),
                )
            logger.error("Gemini API client error on attempt %d: %s", attempt, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Gemini API error: {exc}",
            )

        except Exception as exc:
            # Unexpected errors (network, etc.) -> fail immediately
            logger.error("Gemini unexpected error on attempt %d: %s", attempt, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Gemini API error: {exc}",
            )

    # -- All retries exhausted --
    logger.error(
        "All %d Gemini attempts failed for selection_id=%d. Last error: %s",
        MAX_RETRIES, selection_id, last_error,
    )
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "message": f"Gemini returned invalid JSON after {MAX_RETRIES} attempts.",
            "last_error": last_error,
            "last_raw_response_preview": last_raw[:500],
        },
    )
