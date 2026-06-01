# Extraction Demo Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four backend extraction endpoints — table extraction, document→Markdown, key-value/field extraction, and detailed accessibility alt-text — built on the VLM+Claude engine, with optional OpenAI provider parity.

**Architecture:** Generalize the existing `_run_vision` core in `app/services/extraction.py` to accept `features` and `output_format`, and extract the PDF pre-render logic into a reusable `_prepared_input` context manager. Each new endpoint is a thin preset over that core, following the existing `extract_text_ocr/icr/vlm` wrapper pattern. Routers stay thin, delegating to the service. Three new endpoints (`/tables`, `/markdown`, `/fields`) make live Claude calls; alt-text reuses the existing `/describe` with a newly surfaced `level` knob.

**Tech Stack:** Python 3.12, FastAPI, `nutrient-sdk==1.0.6` (`Vision`, `VisionEngine`, `VisionFeatures`, `VisionOutputFormat`, `DescriptionLevel`, `VlmProvider`), pytest with `fastapi.testclient`.

**Reference spec:** `docs/superpowers/specs/2026-06-01-extraction-demos-design.md`

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `app/services/extraction.py` | All Vision wrappers + new preset functions + shared core | Modify |
| `app/routers/extraction.py` | Thin HTTP handlers for the new endpoints | Modify |
| `tests/conftest.py` | Shared fixtures + provider skip markers | Modify |
| `tests/fixtures/usenix-paper.pdf` | Multi-section doc for the Markdown test | Create (copy) |
| `tests/test_extraction_tables.py` | Table endpoint tests | Create |
| `tests/test_extraction_markdown.py` | Markdown endpoint tests | Create |
| `tests/test_extraction_fields.py` | Field-extraction endpoint tests | Create |
| `tests/test_extraction.py` | Add `level=detailed` describe test | Modify |
| `README.md` | Document the new endpoints | Modify |
| `HANDOFF.md` | Record the new demos + any KEY_VALUE findings | Modify |

Existing fixture `tests/fixtures/ocr-invoice.pdf` is reused for the tables and fields tests (the spike confirmed it yields `table` elements via Claude).

---

## Task 1: Refactor the Vision core (behavior-preserving)

Extract PDF pre-render into a context manager, generalize `_run_vision`/`_extract_with_engine` to take `features` + `output_format`, and make `describe_image` pre-render PDFs and accept a `level`. No endpoint behavior changes yet — existing tests must still pass.

**Files:**
- Modify: `app/services/extraction.py`

- [ ] **Step 1: Run the existing extraction suite to establish a green baseline**

Run: `.venv/bin/pytest tests/test_extraction.py -v`
Expected: PASS (live-Claude tests pass if `ANTHROPIC_API_KEY` is set; the local-VLM 503 test passes regardless).

- [ ] **Step 2: Update imports at the top of `app/services/extraction.py`**

Replace the current import block:

```python
import json
import tempfile
import os

from nutrient_sdk import Document, Vision, VisionEngine, VisionFeatures
```

with:

```python
import contextlib
import json
import tempfile
import os

from nutrient_sdk import (
    Document,
    Vision,
    VisionEngine,
    VisionFeatures,
    VisionOutputFormat,
    DescriptionLevel,
)
```

- [ ] **Step 3: Add the `_prepared_input` context manager**

Insert immediately after the `_LICENSED_VISION_FEATURES` definition (after line 18):

```python
@contextlib.contextmanager
def _prepared_input(image_bytes: bytes, original_filename: str):
    """Write bytes to a temp file and yield a path safe for Vision.

    PDFs are pre-rendered to a single PNG first. Image-only PDFs fail Vision's
    InputImage stage, and once one Vision call fails the SDK enters a process-wide
    bad state where every subsequent call fails identically. Pre-rendering avoids
    triggering that path. Only the first page is rasterized. See
    docs/sdk-feedback/bug-reports/.
    """
    is_pdf = image_bytes[:4] == b"%PDF"
    with tempfile.NamedTemporaryFile(suffix="-" + original_filename, delete=False) as inp:
        inp.write(image_bytes)
        inp_path = inp.name

    rendered_path: str | None = None
    try:
        if is_pdf:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as out:
                rendered_path = out.name
            with Document.open(inp_path) as doc:
                doc.export_as_image(rendered_path)
            yield rendered_path
        else:
            yield inp_path
    finally:
        os.unlink(inp_path)
        if rendered_path and os.path.exists(rendered_path):
            os.unlink(rendered_path)
```

- [ ] **Step 4: Replace `_extract_with_engine` with a thin wrapper over a new `_run_with_prerender`**

Replace the entire existing `_extract_with_engine` function (lines 76-109) with:

```python
def _run_with_prerender(
    image_bytes: bytes,
    original_filename: str,
    engine: str,
    *,
    provider: str | None = None,
    features: int | None = None,
    output_format: "VisionOutputFormat | None" = None,
) -> str:
    """Pre-render if needed, then run Vision and return the raw extract string."""
    with _prepared_input(image_bytes, original_filename) as path:
        return _run_vision(
            path,
            engine,
            provider=provider,
            features=features,
            output_format=output_format,
        )


def _extract_with_engine(
    image_bytes: bytes,
    original_filename: str,
    engine: str,
    *,
    provider: str | None = None,
) -> dict:
    raw_json = _run_with_prerender(image_bytes, original_filename, engine, provider=provider)
    return _format_extraction_result(raw_json, original_filename, engine)
```

- [ ] **Step 5: Generalize `_run_vision` to accept `features` and `output_format`**

Replace the `_run_vision` signature and the two setup lines. The current head is:

```python
def _run_vision(path: str, engine: str, *, provider: str | None = None) -> str:
    with Document.open(path) as doc:
        s = doc.get_settings()
        vs = s.get_vision_settings()
        engine_map = {
            "OCR": VisionEngine.ADAPTIVE_OCR,
            "ICR": VisionEngine.ICR,
            "VLM": VisionEngine.VLM_ENHANCED_ICR,
        }
        vs.set_engine(engine_map[engine])
        vs.set_features(_LICENSED_VISION_FEATURES)
```

Replace it with:

```python
def _run_vision(
    path: str,
    engine: str,
    *,
    provider: str | None = None,
    features: int | None = None,
    output_format: "VisionOutputFormat | None" = None,
) -> str:
    with Document.open(path) as doc:
        s = doc.get_settings()
        vs = s.get_vision_settings()
        engine_map = {
            "OCR": VisionEngine.ADAPTIVE_OCR,
            "ICR": VisionEngine.ICR,
            "VLM": VisionEngine.VLM_ENHANCED_ICR,
        }
        vs.set_engine(engine_map[engine])
        vs.set_features(features if features is not None else _LICENSED_VISION_FEATURES)
        if output_format is not None:
            vs.set_output_format(output_format)
```

Leave the rest of `_run_vision` (the `if provider:` block and the `try/except LocalVlmUnavailable`) unchanged.

- [ ] **Step 6: Make `describe_image` pre-render PDFs and accept a `level`**

Replace the entire existing `describe_image` function (lines 33-73) with:

```python
def describe_image(
    image_bytes: bytes,
    original_filename: str,
    *,
    prompt: str | None = None,
    provider: str = "claude",
    level: str = "standard",
) -> dict:
    """Run Vision.describe() with an optional custom prompt, provider, and detail level."""
    from nutrient_sdk.vlmprovider import VlmProvider

    level_map = {
        "standard": DescriptionLevel.STANDARD,
        "detailed": DescriptionLevel.DETAILED,
    }
    level_key = level.lower()
    if level_key not in level_map:
        raise ValueError(f"Unsupported level: {level}")

    with _prepared_input(image_bytes, original_filename) as path:
        with Document.open(path) as doc:
            s = doc.get_settings()
            s.get_vision_descriptor_settings().set_level(level_map[level_key])
            if prompt:
                s.get_vision_descriptor_settings().set_standard_prompt(prompt)
            p = provider.lower()
            if p == "claude":
                s.get_vision_settings().set_provider(VlmProvider.CLAUDE)
                s.get_claude_api_settings().set_api_key(os.environ["ANTHROPIC_API_KEY"])
            elif p == "openai":
                s.get_vision_settings().set_provider(VlmProvider.OPEN_AI)
                s.get_open_ai_api_endpoint_settings().set_api_key(os.environ["OPENAI_API_KEY"])
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            vision = Vision.set(doc)
            text = vision.describe()

    return {
        "engine": "VLM_DESCRIBE",
        "filename": original_filename,
        "provider": p,
        "level": level_key,
        "promptUsed": prompt or "(default)",
        "text": text,
    }
```

- [ ] **Step 7: Run the existing suite to confirm no behavior change**

Run: `.venv/bin/pytest tests/test_extraction.py -v`
Expected: PASS — same results as Step 1. The describe test now also returns a `level` key (verified in Task 5); existing assertions are unaffected.

- [ ] **Step 8: Commit**

```bash
git add app/services/extraction.py
git commit -m "refactor(extraction): generalize Vision core with features/output_format

Extract PDF pre-render into _prepared_input context manager, add
features/output_format params to the Vision core, and make describe_image
pre-render PDFs and accept a detail level. Behavior-preserving."
```

---

## Task 2: Table extraction endpoint

**Files:**
- Modify: `app/services/extraction.py`
- Modify: `app/routers/extraction.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_extraction_tables.py`

- [ ] **Step 1: Add provider skip markers + invoice fixture path to `tests/conftest.py`**

Append to `tests/conftest.py`:

```python
import os

OCR_INVOICE = Path(__file__).resolve().parent / "fixtures" / "ocr-invoice.pdf"

requires_anthropic = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
requires_openai = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


@pytest.fixture
def invoice_pdf_bytes() -> bytes:
    return OCR_INVOICE.read_bytes()
```

(`Path`, `pytest`, and `app.main` are already imported at the top of `conftest.py`; importing `app.main` runs `load_dotenv()` via `app.config`, so the env vars are populated before these markers evaluate.)

- [ ] **Step 2: Write the failing test `tests/test_extraction_tables.py`**

```python
from fastapi.testclient import TestClient

from tests.conftest import requires_anthropic


@requires_anthropic
def test_tables_endpoint_returns_structured_tables(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/tables",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_TABLES"
    assert body["provider"] == "claude"
    assert body["tableCount"] >= 1
    first = body["tables"][0]
    assert first["rowCount"] >= 1
    assert first["columnCount"] >= 1
    assert len(first["cells"]) >= 1
    cell = first["cells"][0]
    assert {"row", "column", "rowSpan", "colSpan", "text", "confidence", "bounds"} <= set(cell)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_extraction_tables.py -v`
Expected: FAIL with 404 / `KeyError` (endpoint not defined yet). If `ANTHROPIC_API_KEY` is unset, expected SKIPPED — set the key to exercise this task.

- [ ] **Step 4: Add `extract_tables` + `_format_tables` to `app/services/extraction.py`**

Insert after the `describe_image` function:

```python
def _format_tables(raw_json: str, filename: str, provider: str) -> dict:
    parsed = json.loads(raw_json)
    elements = parsed.get("elements", [])
    tables = [e for e in elements if str(e.get("type", "")).lower() == "table"]
    return {
        "engine": "VLM_TABLES",
        "filename": filename,
        "provider": provider,
        "tableCount": len(tables),
        "tables": [
            {
                "rowCount": t.get("rowCount"),
                "columnCount": t.get("columnCount"),
                "cells": [
                    {
                        "row": c.get("row"),
                        "column": c.get("column"),
                        "rowSpan": c.get("rowSpan"),
                        "colSpan": c.get("colSpan"),
                        "text": c.get("text"),
                        "confidence": round(c.get("confidence", 0), 2),
                        "bounds": c.get("bounds"),
                    }
                    for c in t.get("cells", [])
                ],
            }
            for t in tables
        ],
        "rawElements": elements,
    }


def extract_tables(image_bytes: bytes, original_filename: str, provider: str = "claude") -> dict:
    raw = _run_with_prerender(
        image_bytes,
        original_filename,
        "VLM",
        provider=provider,
        features=VisionFeatures.TABLE.value,
    )
    return _format_tables(raw, original_filename, provider)
```

- [ ] **Step 5: Add the `/tables` route to `app/routers/extraction.py`**

Add `extract_tables` to the import block from `app.services.extraction`, then append:

```python
@router.post("/tables")
async def tables(
    file: UploadFile = File(...),
    provider: str = Query("claude", description="VLM provider: 'claude' or 'openai'."),
):
    try:
        data = await file.read()
        return extract_tables(data, file.filename or "input", provider=provider)
    except LocalVlmUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_extraction_tables.py -v`
Expected: PASS (with `ANTHROPIC_API_KEY` set).

- [ ] **Step 7: Commit**

```bash
git add app/services/extraction.py app/routers/extraction.py tests/conftest.py tests/test_extraction_tables.py
git commit -m "feat(extraction): add /api/extraction/tables endpoint

Structured table extraction via VLM_ENHANCED_ICR + TABLE feature, returning
rowCount/columnCount/cells per table. Claude provider by default."
```

---

## Task 3: Document → Markdown endpoint

**Files:**
- Modify: `app/services/extraction.py`
- Modify: `app/routers/extraction.py`
- Create: `tests/fixtures/usenix-paper.pdf`
- Test: `tests/test_extraction_markdown.py`

- [ ] **Step 1: Copy the multi-section sample doc into fixtures**

Run:
```bash
cp "/Users/jonaddamsnutrient/SE/code/nutrient-sdk-samples/public/documents/usenix-example-paper.pdf" tests/fixtures/usenix-paper.pdf
```
Expected: file exists at `tests/fixtures/usenix-paper.pdf`. (If the companion repo path differs, use any committed multi-section PDF; the test only needs a heading and a table to appear in the Markdown.)

- [ ] **Step 2: Write the failing test `tests/test_extraction_markdown.py`**

```python
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import requires_anthropic

USENIX_PDF = Path(__file__).resolve().parent / "fixtures" / "usenix-paper.pdf"


@requires_anthropic
def test_markdown_endpoint_returns_markdown(client: TestClient):
    response = client.post(
        "/api/extraction/markdown",
        files={"file": (USENIX_PDF.name, USENIX_PDF.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_MARKDOWN"
    assert body["provider"] == "claude"
    assert body["charCount"] > 0
    assert body["charCount"] == len(body["markdown"])
    assert "#" in body["markdown"]  # at least one heading
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_extraction_markdown.py -v`
Expected: FAIL with 404 (endpoint not defined). SKIPPED if no key.

- [ ] **Step 4: Add `extract_markdown` to `app/services/extraction.py`**

Insert after `extract_tables`:

```python
def extract_markdown(image_bytes: bytes, original_filename: str, provider: str = "claude") -> dict:
    md = _run_with_prerender(
        image_bytes,
        original_filename,
        "VLM",
        provider=provider,
        features=VisionFeatures.TABLE.value,
        output_format=VisionOutputFormat.MARKDOWN,
    )
    return {
        "engine": "VLM_MARKDOWN",
        "filename": original_filename,
        "provider": provider,
        "markdown": md,
        "charCount": len(md),
    }
```

- [ ] **Step 5: Add the `/markdown` route to `app/routers/extraction.py`**

Add `extract_markdown` to the service import block, then append:

```python
@router.post("/markdown")
async def markdown(
    file: UploadFile = File(...),
    provider: str = Query("claude", description="VLM provider: 'claude' or 'openai'."),
):
    try:
        data = await file.read()
        return extract_markdown(data, file.filename or "input", provider=provider)
    except LocalVlmUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_extraction_markdown.py -v`
Expected: PASS (with key set).

- [ ] **Step 7: Commit**

```bash
git add app/services/extraction.py app/routers/extraction.py tests/fixtures/usenix-paper.pdf tests/test_extraction_markdown.py
git commit -m "feat(extraction): add /api/extraction/markdown endpoint

Document-to-Markdown via the MARKDOWN VisionOutputFormat on the VLM engine.
Returns clean Markdown for RAG/LLM ingestion pipelines."
```

---

## Task 4: Key-value / field extraction endpoint (native + schema)

**Files:**
- Modify: `app/services/extraction.py`
- Modify: `app/routers/extraction.py`
- Test: `tests/test_extraction_fields.py`

- [ ] **Step 1: Write the failing test `tests/test_extraction_fields.py`**

```python
from fastapi.testclient import TestClient

from tests.conftest import requires_anthropic


@requires_anthropic
def test_fields_endpoint_extracts_requested_schema_fields(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/fields",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
        data={"fields": "invoice_number, total, billing_date"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_FIELDS"
    assert body["provider"] == "claude"
    assert body["requestedFields"] == ["invoice_number", "total", "billing_date"]
    # Schema path returns either a parsed object with the requested keys, or a parseError.
    if "parseError" not in body:
        assert set(body["schemaFields"].keys()) == {"invoice_number", "total", "billing_date"}
    # Native KEY_VALUE_REGION path must return without error (may be empty if the
    # feature is a no-op on this doc — that is itself a finding, see plan risk #1).
    assert isinstance(body["nativeRegions"], list)


@requires_anthropic
def test_fields_endpoint_accepts_json_array_fields(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/fields",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
        data={"fields": '["invoice_number", "total"]'},
    )
    assert response.status_code == 200, response.text
    assert response.json()["requestedFields"] == ["invoice_number", "total"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_extraction_fields.py -v`
Expected: FAIL with 404 (endpoint not defined). SKIPPED if no key.

- [ ] **Step 3: Add the field-extraction helpers + `extract_fields` to `app/services/extraction.py`**

Insert after `extract_markdown`:

```python
def parse_field_names(raw: str) -> list[str]:
    """Accept a comma-separated list or a JSON array of field names."""
    raw = raw.strip()
    if raw.startswith("["):
        return [str(x).strip() for x in json.loads(raw) if str(x).strip()]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _strip_code_fence(text: str) -> str:
    """Remove a leading/trailing ```json ... ``` fence if the model added one."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_native_kv(elements: list[dict]) -> list[dict]:
    """Pull elements the SDK tagged as key-value regions. Lenient: matches on
    'key'/'value' appearing in the element type or role."""
    regions = []
    for e in elements:
        marker = (str(e.get("type", "")) + " " + str(e.get("role", ""))).lower()
        if "key" in marker or "value" in marker:
            regions.append(
                {
                    "text": e.get("text"),
                    "type": e.get("type"),
                    "role": e.get("role"),
                    "confidence": round(e.get("confidence", 0), 2),
                    "bounds": e.get("bounds"),
                }
            )
    return regions


def _extract_schema_fields(
    image_bytes: bytes,
    original_filename: str,
    fields: list[str],
    provider: str,
) -> tuple[dict, str | None]:
    """Schema-driven extraction via a custom describe() prompt. Returns
    (parsed_fields, parse_error). On parse failure, parsed_fields is {} and
    parse_error holds the raw model text."""
    field_list = ", ".join(fields)
    prompt = (
        "Extract the following fields from this document and return ONLY a JSON "
        f"object with these exact keys: {field_list}. Use null for any field you "
        "cannot find. Do not include any text, explanation, or code fence outside "
        "the JSON object."
    )
    result = describe_image(image_bytes, original_filename, prompt=prompt, provider=provider)
    text = _strip_code_fence(result["text"])
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, None
        return {}, text
    except (ValueError, json.JSONDecodeError):
        return {}, text


def extract_fields(
    image_bytes: bytes,
    original_filename: str,
    fields: list[str],
    provider: str = "claude",
) -> dict:
    raw = _run_with_prerender(
        image_bytes,
        original_filename,
        "VLM",
        provider=provider,
        features=VisionFeatures.KEY_VALUE_REGION.value,
    )
    elements = json.loads(raw).get("elements", [])
    native_regions = _extract_native_kv(elements)
    schema_fields, parse_error = _extract_schema_fields(
        image_bytes, original_filename, fields, provider
    )
    result = {
        "engine": "VLM_FIELDS",
        "filename": original_filename,
        "provider": provider,
        "requestedFields": fields,
        "schemaFields": schema_fields,
        "nativeRegions": native_regions,
        "rawElements": elements,
    }
    if parse_error is not None:
        result["parseError"] = parse_error
    return result
```

- [ ] **Step 4: Add the `/fields` route to `app/routers/extraction.py`**

Add `extract_fields` and `parse_field_names` to the service import block, then append:

```python
@router.post("/fields")
async def fields(
    file: UploadFile = File(...),
    fields: str = Form(..., description="Comma-separated list or JSON array of field names."),
    provider: str = Query("claude", description="VLM provider: 'claude' or 'openai'."),
):
    try:
        data = await file.read()
        names = parse_field_names(fields)
        return extract_fields(data, file.filename or "input", names, provider=provider)
    except LocalVlmUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_extraction_fields.py -v`
Expected: PASS (with key set).

- [ ] **Step 6: Note the native KEY_VALUE_REGION finding**

Inspect the test output / add a quick manual check: if `nativeRegions` is consistently empty across the invoice and a form doc, that confirms `KEY_VALUE_REGION` is a no-op on the local pipeline. Record it in `HANDOFF.md` in Task 7 and consider a `docs/sdk-feedback/` note. No code change required here.

- [ ] **Step 7: Commit**

```bash
git add app/services/extraction.py app/routers/extraction.py tests/test_extraction_fields.py
git commit -m "feat(extraction): add /api/extraction/fields endpoint

Key-value extraction two ways: native KEY_VALUE_REGION regions plus
schema-driven JSON extraction via a custom describe() prompt. Defensive
JSON parsing surfaces parseError instead of 500ing."
```

---

## Task 5: Detailed alt-text via the `/describe` `level` knob

**Files:**
- Modify: `app/routers/extraction.py`
- Modify: `tests/test_extraction.py`

The service already supports `level` (Task 1, Step 6). This task surfaces it on the route and tests it.

- [ ] **Step 1: Write the failing test — append to `tests/test_extraction.py`**

```python
from tests.conftest import requires_anthropic


@requires_anthropic
def test_describe_endpoint_detailed_level(client: TestClient, sample_image_bytes: bytes, sample_image_name: str):
    response = client.post(
        "/api/extraction/describe",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
        data={"provider": "claude", "level": "detailed"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_DESCRIBE"
    assert body["level"] == "detailed"
    assert isinstance(body["text"], str) and len(body["text"]) > 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_extraction.py::test_describe_endpoint_detailed_level -v`
Expected: FAIL — the route does not yet accept `level`, so `body["level"]` is `"standard"` (the service default), not `"detailed"`. SKIPPED if no key.

- [ ] **Step 3: Add the `level` form param to the `/describe` route in `app/routers/extraction.py`**

Replace the existing `describe` route function with:

```python
@router.post("/describe")
async def describe(
    file: UploadFile = File(...),
    prompt: str | None = Form(None),
    provider: str = Form("claude"),
    level: str = Form("standard", description="Description level: 'standard' or 'detailed'."),
):
    try:
        data = await file.read()
        return describe_image(data, file.filename or "input", prompt=prompt, provider=provider, level=level)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_extraction.py::test_describe_endpoint_detailed_level -v`
Expected: PASS (with key set).

- [ ] **Step 5: Commit**

```bash
git add app/routers/extraction.py tests/test_extraction.py
git commit -m "feat(extraction): surface description level on /api/extraction/describe

Adds level=standard|detailed for WCAG-style accessibility alt-text."
```

---

## Task 6: OpenAI provider parity tests

Gated behind `OPENAI_API_KEY`. Asserts the OpenAI path returns the same envelope shape as Claude for `tables` and `fields`.

**Files:**
- Modify: `tests/test_extraction_tables.py`
- Modify: `tests/test_extraction_fields.py`

- [ ] **Step 1: Append an OpenAI parity test to `tests/test_extraction_tables.py`**

```python
from tests.conftest import requires_openai


@requires_openai
def test_tables_endpoint_openai_provider_returns_same_shape(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/tables?provider=openai",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_TABLES"
    assert body["provider"] == "openai"
    assert "tables" in body and isinstance(body["tables"], list)
```

- [ ] **Step 2: Append an OpenAI parity test to `tests/test_extraction_fields.py`**

```python
from tests.conftest import requires_openai


@requires_openai
def test_fields_endpoint_openai_provider_returns_same_shape(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/fields?provider=openai",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
        data={"fields": "invoice_number, total"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_FIELDS"
    assert body["provider"] == "openai"
    assert isinstance(body["nativeRegions"], list)
```

- [ ] **Step 3: Run the parity tests**

Run: `.venv/bin/pytest tests/test_extraction_tables.py tests/test_extraction_fields.py -v -k openai`
Expected: PASS if `OPENAI_API_KEY` is set and valid; otherwise SKIPPED. If the key is present but the calls fail, that is a real OpenAI-path finding — record it rather than weakening the test.

- [ ] **Step 4: Re-run the pending OpenAI ICR parity comparison (unblocks backlog Task 2)**

Once `OPENAI_API_KEY` is valid in `.env`, follow `docs/superpowers/plans/2026-05-29-icr-followup-investigations.md` Task 2 Step 2 to complete the previously-blocked parity comparison. Capture the result in that doc. (No code change in this repo.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_extraction_tables.py tests/test_extraction_fields.py
git commit -m "test(extraction): add OpenAI provider parity tests

Gated on OPENAI_API_KEY; assert the OpenAI path returns the same envelope
shape as Claude for tables and fields."
```

---

## Task 7: Documentation

**Files:**
- Modify: `README.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Add the new endpoints to the README endpoint table**

In `README.md`, in the `extraction` rows of the endpoints table (after the `/vlm` row), add:

```markdown
| `extraction` | `POST /api/extraction/tables` | Structured table extraction (VLM + Claude/OpenAI) |
| `extraction` | `POST /api/extraction/markdown` | Document → clean Markdown for RAG/LLM ingestion |
| `extraction` | `POST /api/extraction/fields` | Key-value extraction: native regions + schema-driven JSON |
```

Also update the existing `/vlm` row to note `?provider=claude|openai` and add a `/describe` row if absent:

```markdown
| `extraction` | `POST /api/extraction/describe` | Custom-prompt transcription / alt-text (`level=standard\|detailed`) |
```

- [ ] **Step 2: Update the README test-time note**

In `README.md`, change the `make test` description from `~12s` to `~70s` to match reality (the SDK is heavy).

- [ ] **Step 3: Update HANDOFF.md**

In `HANDOFF.md`, add the four new demos to the "What the demo currently shows" table, and under "Known SDK issues" record the `KEY_VALUE_REGION` finding from Task 4 Step 6 (no-op or functional, whichever was observed).

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all tests PASS or SKIPPED (skips only where API keys are absent). No failures.

- [ ] **Step 5: Commit**

```bash
git add README.md HANDOFF.md
git commit -m "docs: document new extraction endpoints and KEY_VALUE_REGION finding"
```

---

## Done criteria

- `/api/extraction/tables`, `/markdown`, and `/fields` return the documented envelopes with `provider=claude`.
- `/api/extraction/describe` honors `level=detailed`.
- All three new VLM endpoints accept `?provider=openai` and return the same shape (verified when `OPENAI_API_KEY` is valid).
- `.venv/bin/pytest -v` is green (skips allowed only for absent keys).
- README and HANDOFF document the new endpoints; the `KEY_VALUE_REGION` finding is recorded.
- Frontend pages remain a paired follow-up in `nutrient-sdk-samples` (out of scope here).
