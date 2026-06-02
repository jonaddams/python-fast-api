# SDK Defect-Hunting Test Suite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a rigorous, process-isolated test suite that drives `nutrient_sdk` directly across its full surface, asserts *correct* behavior, and records known defects as `xfail` linked to a defect registry — so the SDK's bugs are found here, with clean repros, before customers hit them.

**Architecture:** A new `tests/sdk/` package, separate from the functional `tests/`. Tests import `nutrient_sdk` directly (no FastAPI). Each capability-area file has three classes — `TestBaseline`, `TestEdgeCases`, `TestSequential`. Every test runs in its own forked process (`pytest-forked`) so the SDK's process-wide state corruption and native SIGSEGVs can't cascade. Known defects use a `defect(id, reason)` helper wrapping `pytest.mark.xfail(strict=True)`, each linked to `docs/sdk-feedback/DEFECTS.md`.

**Tech Stack:** Python 3.12, pytest 9, `pytest-forked` (new dev dep), `python-dotenv`, `nutrient-sdk==1.0.6`.

**Source of truth:** The verified API map at `docs/superpowers/specs/` companion + the workflow introspection results. Every happy-path snippet below was executed against the installed SDK and the real `tests/fixtures/`. Every edge case lists the expected clean behavior and (where known) the verified actual behavior.

---

## Pre-flight findings (read before starting)

The API-mapping pass already surfaced ~39 candidate defects (seeded into `DEFECTS.md` in Task 1). Two are **bugs in shipped repo code, not the SDK** — handle these out of band, they are not part of this suite:

- `app/services/redaction.py:24` calls `pages.get_item(page_index)` — `PdfPageCollection` has **no** `get_item` method (it's `get_page`), so the real redaction endpoint raises `AttributeError`. There is zero test coverage for redaction. **Flag to maintainer.**
- Same service uses a 0-based page index, but `get_page` is **1-based**. **Flag to maintainer.**

Do not fix these inside this plan — note them and keep the suite focused on the SDK.

---

## Conventions used in every task

- License registration per forked child happens in an autouse fixture (Task 1). Tests never call `License.register_key` directly.
- Fixtures dir: `tests/fixtures/` — available files: `account-registration-form.pdf` (1 page, 15 form fields, 40 annotations), `input_forms_detection.pdf`, `input_ocr_multiple_languages.png`, `ocr-invoice.pdf` (image-only/scanned), `usenix-paper.pdf`. (`usenix-paper.pdf` exists; the annotation agent mis-reported it absent — verify in Task 1.)
- All exception types are under `nutrient_sdk` (e.g. `nutrient_sdk.IndexOutOfBoundsException`). The base is `nutrient_sdk.NutrientException`.
- A "clean failure" = a typed `NutrientException` subclass. A bare Python `TypeError`/`ValueError`/`IndexError`, a native `Arg_NullReferenceException` wrapped in `InitializationError`, a SIGSEGV, or silently-wrong output are all defects.

---

## Task 1: Scaffolding, fork-safety spike, and defect registry

**Files:**
- Modify: `pyproject.toml` (add `pytest-forked` dev dep + `tests/sdk` pytest config)
- Modify: `Makefile` (add `test-sdk` target)
- Create: `tests/sdk/__init__.py`
- Create: `tests/sdk/conftest.py`
- Create: `tests/sdk/_support/__init__.py`
- Create: `tests/sdk/_support/inputs.py`
- Create: `tests/sdk/_support/assertions.py`
- Create: `tests/sdk/_support/markers.py`
- Create: `tests/sdk/test_smoke.py`
- Create: `tests/sdk/README.md`
- Create: `docs/sdk-feedback/DEFECTS.md`

- [ ] **Step 1: Add the dev dependency and pin it**

Run: `.venv/bin/pip install pytest-forked && .venv/bin/pip show pytest-forked | head -2`
Expected: a version prints (e.g. `1.6.0`). Then add to `pyproject.toml` under `[project.optional-dependencies] dev`:

```toml
dev = [
    "pytest>=8.0",
    "httpx>=0.27.0",
    "pytest-forked>=1.6.0",
]
```

- [ ] **Step 2: Write the fork-safety spike test**

This is the gating check: it deliberately triggers the process-wide Vision corruption defect in one test, and asserts a *separate* test still gets a clean SDK on a good input — proving fork isolation works.

Create `tests/sdk/test_smoke.py`:

```python
"""Fork-safety spike + suite smoke test.

If these two tests pass under --forked but the corruption test poisons the
clean test when run WITHOUT --forked, that proves isolation is load-bearing
and correctly configured.
"""
import json
from pathlib import Path

from nutrient_sdk import Document, Vision, VisionEngine, VisionFeatures

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
GOOD_PNG = FIXTURES / "input_ocr_multiple_languages.png"
SCANNED_PDF = FIXTURES / "ocr-invoice.pdf"
LICENSED_FEATURES = VisionFeatures.ALL.value - VisionFeatures.FORM.value


def _ocr(path: Path) -> list:
    with Document.open(str(path)) as doc:
        vs = doc.get_settings().get_vision_settings()
        vs.set_engine(VisionEngine.ADAPTIVE_OCR)
        vs.set_features(LICENSED_FEATURES)
        raw = Vision.set(doc).extract_content()
    return json.loads(raw)["elements"]


def test_smoke_ocr_on_png_succeeds():
    elements = _ocr(GOOD_PNG)
    assert len(elements) > 0


def test_fork_isolation_contains_vision_corruption():
    # This test triggers the known image-only-PDF Vision defect. Under --forked
    # it dies in its own child and CANNOT poison test_smoke_ocr_on_png_succeeds.
    import pytest
    with pytest.raises(Exception):
        _ocr(SCANNED_PDF)
```

- [ ] **Step 3: Configure pytest so `tests/sdk` runs forked**

Add a dedicated config block to `pyproject.toml`. Keep the existing `tests/` behavior unchanged — `--forked` is passed only by the `make test-sdk` target, not globally, so the functional suite stays fast:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-p no:faulthandler"
markers = [
    "sdk_defect: marks a test that documents a known SDK defect (see docs/sdk-feedback/DEFECTS.md)",
]
```

- [ ] **Step 4: Add the Makefile target**

Add to `Makefile`:

```makefile
test-sdk:  ## Run the SDK defect-hunting suite (process-isolated)
	.venv/bin/pytest tests/sdk/ --forked -v -rxX
```

(`-rxX` prints the xfail/xpass summary so known defects and newly-fixed ones are visible.)

- [ ] **Step 5: Run the spike under fork isolation**

Run: `.venv/bin/pytest tests/sdk/test_smoke.py --forked -v -rxX`
Expected: `test_smoke_ocr_on_png_succeeds PASSED` and `test_fork_isolation_contains_vision_corruption PASSED`. Both pass because each ran in its own process.

- [ ] **Step 6: Prove isolation is necessary (run WITHOUT --forked)**

Run: `.venv/bin/pytest tests/sdk/test_smoke.py -v` (no `--forked`)
Expected: ordering-dependent failure — if the corruption test runs first, the OCR test fails too (process poisoned). This confirms `--forked` is load-bearing. Document the observed result in `tests/sdk/README.md`. (If both pass even without `--forked`, the corruption no longer reproduces in-process — note that and still keep `--forked` for SIGSEGV containment.)

- [ ] **Step 7: Write the per-child license fixture**

Create `tests/sdk/conftest.py`:

```python
"""Per-forked-child SDK setup + shared fixtures for the defect-hunting suite."""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

load_dotenv(PROJECT_ROOT / ".env")


@pytest.fixture(autouse=True)
def _register_license():
    """Each forked child is a fresh process and must register the license."""
    from nutrient_sdk import License
    key = os.environ.get("NUTRIENT_LICENSE_KEY")
    if not key:
        pytest.skip("NUTRIENT_LICENSE_KEY not set")
    License.register_key(key)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def account_form(fixtures_dir) -> str:
    return str(fixtures_dir / "account-registration-form.pdf")


@pytest.fixture
def detection_pdf(fixtures_dir) -> str:
    return str(fixtures_dir / "input_forms_detection.pdf")


@pytest.fixture
def ocr_png(fixtures_dir) -> str:
    return str(fixtures_dir / "input_ocr_multiple_languages.png")


@pytest.fixture
def scanned_pdf(fixtures_dir) -> str:
    return str(fixtures_dir / "ocr-invoice.pdf")


requires_anthropic = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
requires_openai = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"
)
```

- [ ] **Step 8: Write the bad-input generators**

Create `tests/sdk/_support/inputs.py`:

```python
"""Generators for malformed / edge-case inputs, written to temp files."""
import os
import tempfile
from pathlib import Path


def _tmp(suffix: str, data: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def empty_file(suffix: str = ".pdf") -> str:
    """A zero-byte file with the given extension."""
    return _tmp(suffix, b"")


def wrong_magic(suffix: str = ".pdf") -> str:
    """A file whose contents are not the format its extension claims."""
    return _tmp(suffix, b"this is definitely not a real document at all")


def truncated_pdf() -> str:
    """A file that starts like a PDF then stops."""
    return _tmp(".pdf", b"%PDF-1.7\n1 0 obj<< /Type /Catalog")


def png_renamed_pdf(fixtures_dir: Path) -> str:
    """A real PNG's bytes under a .pdf extension."""
    data = (fixtures_dir / "input_ocr_multiple_languages.png").read_bytes()
    return _tmp(".pdf", data)


def unicode_named_copy(fixtures_dir: Path) -> str:
    """A real PDF copied to a path with a unicode + spaces filename."""
    data = (fixtures_dir / "account-registration-form.pdf").read_bytes()
    d = tempfile.mkdtemp()
    path = os.path.join(d, "ünïcödé 文件 name.pdf")
    Path(path).write_bytes(data)
    return path


def cleanup(*paths: str) -> None:
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass
```

- [ ] **Step 9: Write assertion + marker helpers**

Create `tests/sdk/_support/assertions.py`:

```python
"""Helpers that encode the 'failed cleanly vs crashed/poisoned/silent' judgement."""
import nutrient_sdk


def is_typed_sdk_error(exc: BaseException) -> bool:
    """True if exc is one of the SDK's own typed exceptions."""
    return isinstance(exc, nutrient_sdk.NutrientException)
```

Create `tests/sdk/_support/markers.py`:

```python
"""xfail helper that links a known defect to docs/sdk-feedback/DEFECTS.md."""
import pytest


def defect(defect_id: str, reason: str, *, raises=None):
    """Mark a test as a KNOWN SDK defect.

    strict=True: when the SDK is fixed the test xpasses and the suite goes RED,
    prompting removal of the marker and a DEFECTS.md status update.
    """
    return pytest.mark.xfail(
        reason=f"{defect_id}: {reason}",
        strict=True,
        raises=raises,
    )
```

- [ ] **Step 10: Seed the defect registry**

Create `docs/sdk-feedback/DEFECTS.md` with the candidates already found (table form). Seed rows (ID, area, symptom, severity, status):

```markdown
# Nutrient Python SDK — Defect Registry

Living log of defects found by `tests/sdk/`. Status: `open` (found, not filed),
`filed` (JIRA ticket exists, link it), `fixed` (SDK corrected — remove the xfail).

| ID | Area | Symptom | Severity | Status |
|----|------|---------|----------|--------|
| SDK-001 | Document | `Document.open(None)` / `open(bytes)` raises bare Python `TypeError`, not a typed `NutrientArgumentNullException` | med | open |
| SDK-002 | Document/Conversion/Editor/Forms | Corrupt/empty/wrong-magic file surfaces as `InitializationError('Arg_NullReferenceException', 1006)` instead of `DocumentError` | high | open |
| SDK-003 | Document/Vision/Exporters | Process-wide native state corruption: one failed call poisons all later calls in the process | critical | filed |
| SDK-004 | Document/Conversion/Signing/Exporters | Use-after-close raises bare Python `ValueError`, not typed `InvalidStateException` | med | open |
| SDK-005 | Document | `export_as_image` ignores file extension for format selection | low | open |
| SDK-006 | Document | `export_as_image(None)` raises `InitializationError(EmptyString,1002)` not a null-arg exception | low | open |
| SDK-007 | Editor | `PdfPage` rotation is read-only — no `set_rotation()`/`rotate()` despite "Document Editor API" entitlement | high | open |
| SDK-008 | Editor/Forms/Redaction | `PdfEditor.edit()` twice on one Document does not raise `AlreadyOpenForEditionException` (which exists) | med | open |
| SDK-009 | Editor | `pages.add(width=-5, height=-5)` raises `IndexOutOfBoundsException` instead of `InvalidArgumentException` | med | open |
| SDK-010 | Editor | Editor use-after-close raises `IndexOutOfBoundsException` instead of `InvalidStateException` | med | open |
| SDK-011 | Annotations | `PdfAnnotation.get_rect()` returns an opaque native handle int, not geometry | high | open |
| SDK-012 | Annotations | No public annotation indexer; only private `_get_item` / `get_enumerator` | med | open |
| SDK-013 | Forms | Form-field collection out-of-range raises builtin `IndexError`, not `IndexOutOfBoundsException` | med | open |
| SDK-014 | Forms | `find_by_full_name` returns `None` silently for a missing field | med | open |
| SDK-015 | Forms | `set_value(None)` silently accepted on a text field | med | open |
| SDK-016 | Forms | `set_value('bogus')` on a radio/combo field accepted without option validation | med | open |
| SDK-017 | Forms | `collection[i]` / `find_by_full_name` always return base `PdfFormField`, never the typed subtype | high | open |
| SDK-018 | Forms | `FormRecognitionSettings.set_confidence_threshold` accepts out-of-[0,1] values unvalidated | med | open |
| SDK-019 | Signing | `get_hash_algorithm()` returns raw int, not `SignatureHashAlgorithm` (asymmetric round-trip) | low | open |
| SDK-020 | Signing | `set_hash_algorithm('SHA256')` raises raw ctypes `ArgumentError`, not a typed exception | med | open |
| SDK-021 | Signing | `Signature` use-after-close raises bare Python `ValueError` | med | open |
| SDK-022 | Signing | Wrong password & missing cert both raise generic `SdkException` 3025 (no dedicated cert exception) | med | open |
| SDK-023 | Signing | `sign(doc, None, opts)` raises `InitializationError(1002)` not a null-arg exception | low | open |
| SDK-024 | Redaction/Annotations | `add_redact`/markup factories accept negative/NaN/inf geometry without validation | med | open |
| SDK-025 | Redaction | APPLY_REDACTIONS footgun: default `NONE` leaves underlying content recoverable | high | open |
| SDK-026 | Vision | Image-only/scanned PDF fails at `InputImage` stage with truncated message | high | filed |
| SDK-027 | Vision | VLM-unavailable only detectable by string-matching the message; no typed exception | med | open |
| SDK-028 | Vision | `extraction.py` strips `VisionFeatures.FORM` assuming unlicensed, but `vision_form` is now licensed in 1.0.6 (stale) | low | open |
| SDK-029 | Exporters | Orphaned `*Settings`: no Python API attaches settings to any exporter | high | open |
| SDK-030 | Exporters | `ImageExportFormat` exposes only `TIFF` despite docstring claiming PNG/JPEG/TIFF/BMP | med | open |
| SDK-031 | Exporters | `export()` doesn't guard a closed exporter — NULL handle → native crash | med | open |
| SDK-032 | Conversion | `ConversionSettings.set_timeout_milliseconds(-1)` accepted unvalidated | low | open |
| SDK-033 | Conversion/Exporters | `PresentationSettings` has zero properties (PDF→PPTX tuning incomplete) | low | open |
```

- [ ] **Step 11: Write the suite README**

Create `tests/sdk/README.md` explaining: run with `make test-sdk`; `xfail` = known defect (see DEFECTS.md); `XPASS` (strict) turning the suite red = the SDK fixed a bug, so update DEFECTS.md and remove the marker; new red failures = a freshly-found defect, so add a DEFECTS.md row and a `defect()` marker, then draft a `bug-reports/` filing for high-severity ones.

- [ ] **Step 12: Commit**

```bash
git add pyproject.toml Makefile tests/sdk docs/sdk-feedback/DEFECTS.md
git commit -m "test(sdk): scaffold process-isolated defect-hunting suite + defect registry"
```

---

## Task 2: Document lifecycle (`tests/sdk/test_document.py`)

**Files:**
- Create: `tests/sdk/test_document.py`

- [ ] **Step 1: Write the baseline test (verified happy path)**

```python
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


class TestBaseline:
    def test_open_page_count_settings_export(self, account_form):
        with Document.open(account_form) as doc:
            assert doc.get_page_count() == 1
            assert doc.page_count == 1
            assert doc.get_underlying_type() == 3  # DOCUMENT_TYPE_PDF
            assert type(doc.get_settings()).__name__ == "DocumentSettings"
            editor = PdfEditor.edit(doc)
            pages = editor.get_page_collection()
            assert len(pages) == 1
            p0 = pages[0]
            assert round(p0.get_width(), 1) == 612.0
            assert round(p0.get_height(), 1) == 792.0
            editor.close()
            out = tempfile.mktemp(suffix=".png")
            doc.export_as_image(out)
            assert Path(out).stat().st_size > 0
            inputs.cleanup(out)
```

- [ ] **Step 2: Run baseline**

Run: `.venv/bin/pytest tests/sdk/test_document.py::TestBaseline --forked -v`
Expected: PASS.

- [ ] **Step 3: Write the edge-case class (one test per verified edge)**

```python
class TestEdgeCases:
    @defect("SDK-001", "open(None) raises bare TypeError, not NutrientArgumentNullException")
    def test_open_none_is_typed(self):
        with pytest.raises(nutrient_sdk.NutrientException):
            Document.open(None)

    @defect("SDK-001", "open(bytes) raises bare TypeError, not a typed exception")
    def test_open_bytes_is_typed(self):
        with pytest.raises(nutrient_sdk.NutrientException):
            Document.open(b"%PDF-1.4 fake")

    def test_open_missing_path_is_filenotfound(self):
        with pytest.raises(nutrient_sdk.FileNotFoundException):
            Document.open("/tmp/does_not_exist_xyz_12345.pdf")

    @defect("SDK-002", "wrong-magic file surfaces as InitializationError(1006), not DocumentError")
    def test_open_wrong_magic_is_documenterror(self):
        path = inputs.wrong_magic(".pdf")
        try:
            with pytest.raises(nutrient_sdk.DocumentError):
                Document.open(path)
        finally:
            inputs.cleanup(path)

    @defect("SDK-002", "empty file surfaces as InitializationError(1006), not DocumentError")
    def test_open_empty_file_is_documenterror(self):
        path = inputs.empty_file(".pdf")
        try:
            with pytest.raises(nutrient_sdk.DocumentError):
                Document.open(path)
        finally:
            inputs.cleanup(path)

    @defect("SDK-004", "use-after-close raises bare ValueError, not InvalidStateException")
    def test_use_after_close_is_typed(self, account_form):
        doc = Document.open(account_form)
        doc.close()
        with pytest.raises(nutrient_sdk.InvalidStateException):
            doc.get_page_count()

    def test_double_close_is_noop(self, account_form):
        doc = Document.open(account_form)
        doc.close()
        doc.close()  # must not raise

    def test_export_to_missing_dir_is_typed_io(self, account_form):
        with Document.open(account_form) as doc:
            with pytest.raises(nutrient_sdk.IOError):
                doc.export_as_pdf("/nonexistent_dir_xyz/out.pdf")

    @defect("SDK-006", "export_as_image(None) raises InitializationError(1002), not a null-arg exception")
    def test_export_none_path_is_null_arg(self, account_form):
        with Document.open(account_form) as doc:
            with pytest.raises(nutrient_sdk.NullOrEmptyParameterException):
                doc.export_as_image(None)

    def test_page_index_out_of_range_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                _ = pages[5]
```

- [ ] **Step 4: Run edge cases**

Run: `.venv/bin/pytest tests/sdk/test_document.py::TestEdgeCases --forked -v -rxX`
Expected: non-`defect` tests PASS; `defect`-marked tests show `XFAIL`. If any `defect` test `XPASS`es (strict → fail), the SDK behavior changed — update DEFECTS.md and remove that marker.

- [ ] **Step 5: Write the sequential / stress class**

```python
class TestSequential:
    def test_open_export_loop_no_leak(self, account_form):
        # 30x open->export->close in one process: surfaces handle leaks / growth.
        for _ in range(30):
            with Document.open(account_form) as doc:
                out = tempfile.mktemp(suffix=".pdf")
                doc.export_as_pdf(out)
                assert Path(out).stat().st_size > 0
                inputs.cleanup(out)

    @defect("SDK-003", "a prior failed open poisons later good opens in the same process")
    def test_failed_open_does_not_poison_next(self, account_form):
        bad = inputs.wrong_magic(".pdf")
        try:
            try:
                Document.open(bad)
            except Exception:
                pass
            # A good open afterwards must still succeed cleanly.
            with Document.open(account_form) as doc:
                assert doc.get_page_count() == 1
        finally:
            inputs.cleanup(bad)
```

- [ ] **Step 6: Run the full file**

Run: `.venv/bin/pytest tests/sdk/test_document.py --forked -v -rxX`
Expected: baseline + sequential PASS (note `test_open_export_loop_no_leak` proves no in-process leak even though each *test* is forked); edge/known-defect tests XFAIL.

- [ ] **Step 7: Commit**

```bash
git add tests/sdk/test_document.py
git commit -m "test(sdk): Document lifecycle baseline, edge, and stress coverage"
```

---

## Task 3: Conversion (`tests/sdk/test_conversion.py`)

**Files:**
- Create: `tests/sdk/test_conversion.py`

- [ ] **Step 1: Baseline (verified MD→PDF and PDF→HTML)**

```python
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, DocumentSettings

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


def _write(suffix: str, data: bytes) -> str:
    p = tempfile.mktemp(suffix=suffix)
    Path(p).write_bytes(data)
    return p


class TestBaseline:
    def test_markdown_to_pdf(self):
        src = _write(".md", b"# Hello\n\nThis is **bold**.\n\n- one\n- two\n")
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(src) as doc:
                assert doc.get_underlying_type() == 21  # DOCUMENT_TYPE_MD
                doc.export_as_pdf(out)
            assert Path(out).read_bytes()[:5].startswith(b"%PDF")
        finally:
            inputs.cleanup(src, out)

    def test_pdf_to_html(self, account_form):
        out = tempfile.mktemp(suffix=".html")
        try:
            with Document.open(account_form) as doc:
                doc.export_as_html(out)
            assert Path(out).read_bytes()[:15].startswith(b"<!DOCTYPE html>")
        finally:
            inputs.cleanup(out)
```

- [ ] **Step 2: Run baseline** — `.venv/bin/pytest tests/sdk/test_conversion.py::TestBaseline --forked -v` → PASS.

- [ ] **Step 3: Edge cases**

```python
class TestEdgeCases:
    @defect("SDK-002", "empty .docx surfaces as InitializationError(1006), not ConversionError")
    def test_empty_office_file_is_typed(self):
        path = inputs.empty_file(".docx")
        try:
            with pytest.raises(nutrient_sdk.NutrientException) as ei:
                with Document.open(path) as doc:
                    doc.export_as_pdf(tempfile.mktemp(suffix=".pdf"))
            assert not isinstance(ei.value, nutrient_sdk.InitializationError)
        finally:
            inputs.cleanup(path)

    @defect("SDK-032", "negative conversion timeout accepted without validation")
    def test_negative_timeout_rejected(self):
        src = _write(".md", b"# x\n")
        try:
            s = DocumentSettings()
            s.conversion_settings.set_timeout_milliseconds(-1)
            with pytest.raises(nutrient_sdk.NutrientException):
                with Document.open(src, s) as doc:
                    doc.export_as_pdf(tempfile.mktemp(suffix=".pdf"))
        finally:
            inputs.cleanup(src)

    def test_unsupported_conversion_is_typed(self, ocr_png):
        # Raster image -> spreadsheet has no tabular source; expect a typed error.
        out = tempfile.mktemp(suffix=".xlsx")
        with pytest.raises(nutrient_sdk.NutrientException):
            with Document.open(ocr_png) as doc:
                doc.export_as_spreadsheet(out)
        inputs.cleanup(out)
```

- [ ] **Step 4: Run edge cases** — `.venv/bin/pytest tests/sdk/test_conversion.py::TestEdgeCases --forked -v -rxX`. Non-defect PASS, defect XFAIL.

- [ ] **Step 5: Sequential**

```python
class TestSequential:
    def test_roundtrip_pdf_to_word_to_pdf(self, account_form):
        docx = tempfile.mktemp(suffix=".docx")
        pdf2 = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                doc.export_as_word(docx)
            assert Path(docx).stat().st_size > 0
            with Document.open(docx) as doc:
                doc.export_as_pdf(pdf2)
            assert Path(pdf2).read_bytes()[:5].startswith(b"%PDF")
        finally:
            inputs.cleanup(docx, pdf2)

    def test_repeated_conversions_no_leak(self, account_form):
        for _ in range(20):
            out = tempfile.mktemp(suffix=".md")
            with Document.open(account_form) as doc:
                doc.export_as_markdown(out)
            assert Path(out).stat().st_size > 0
            inputs.cleanup(out)
```

- [ ] **Step 6: Run + commit**

Run: `.venv/bin/pytest tests/sdk/test_conversion.py --forked -v -rxX`

```bash
git add tests/sdk/test_conversion.py
git commit -m "test(sdk): conversion baseline, edge, and roundtrip coverage"
```

---

## Task 4: Editor (`tests/sdk/test_editor.py`)

**Files:**
- Create: `tests/sdk/test_editor.py`

- [ ] **Step 1: Baseline (verified page ops + metadata round-trip)**

```python
import shutil
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


class TestBaseline:
    def test_page_ops_and_metadata_roundtrip(self, account_form):
        work = tempfile.mktemp(suffix=".pdf")
        out = tempfile.mktemp(suffix=".pdf")
        shutil.copy(account_form, work)
        try:
            with Document.open(work) as doc:
                editor = PdfEditor.edit(doc)
                pages = editor.get_page_collection()
                assert pages.get_count() == 1
                pages.add(width=200.0, height=300.0)
                pages.insert(0, width=150.0, height=150.0)
                pages.swap(0, 1)
                pages.move_to(0, pages.get_count() - 1)
                pages.remove_at(pages.get_count() - 1)
                assert pages.get_count() == 2
                editor.get_metadata().set_title("Edited By Test")
                editor.save_as(out)
                editor.close()
            with Document.open(out) as doc2:
                e2 = PdfEditor.edit(doc2)
                assert e2.get_page_collection().get_count() == 2
                assert e2.get_metadata().get_title() == "Edited By Test"
                e2.close()
        finally:
            inputs.cleanup(work, out)
```

- [ ] **Step 2: Run baseline** — `--forked -v` → PASS.

- [ ] **Step 3: Edge cases (verified wrong-type exceptions are the defects)**

```python
class TestEdgeCases:
    def test_get_page_out_of_range_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                pages.get_page(999)

    @defect("SDK-009", "add() with negative dims raises IndexOutOfBoundsException, not InvalidArgumentException")
    def test_add_negative_dims_is_invalid_arg(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                pages.add(width=-5.0, height=-5.0)

    @defect("SDK-010", "editor use-after-close raises IndexOutOfBoundsException, not InvalidStateException")
    def test_editor_use_after_close_is_state_error(self, account_form):
        with Document.open(account_form) as doc:
            editor = PdfEditor.edit(doc)
            editor.close()
            with pytest.raises(nutrient_sdk.InvalidStateException):
                editor.get_page_collection().get_count()

    @defect("SDK-008", "second PdfEditor.edit on one Document does not raise AlreadyOpenForEditionException")
    def test_concurrent_edit_is_guarded(self, account_form):
        with Document.open(account_form) as doc:
            PdfEditor.edit(doc)
            with pytest.raises(nutrient_sdk.AlreadyOpenForEditionException):
                PdfEditor.edit(doc)

    @defect("SDK-002", "edit() on a wrong-magic PDF leaks InitializationError(1006), not DocumentError")
    def test_edit_corrupt_pdf_is_documenterror(self):
        path = inputs.truncated_pdf()
        try:
            with pytest.raises(nutrient_sdk.DocumentError):
                with Document.open(path) as doc:
                    PdfEditor.edit(doc).get_page_collection().get_count()
        finally:
            inputs.cleanup(path)
```

- [ ] **Step 4: Capability-gap test (page rotation is read-only)**

```python
class TestCapabilityGaps:
    @defect("SDK-007", "PdfPage has no set_rotation()/rotate() despite Document Editor entitlement")
    def test_page_rotation_is_settable(self, account_form):
        with Document.open(account_form) as doc:
            page = PdfEditor.edit(doc).get_page_collection().get_first()
            # A real editor API must allow setting rotation. Assert the method exists.
            assert hasattr(page, "set_rotation") or hasattr(page, "rotate")
```

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/pytest tests/sdk/test_editor.py --forked -v -rxX`

```bash
git add tests/sdk/test_editor.py
git commit -m "test(sdk): editor page-ops, metadata, lifecycle, and rotation-gap coverage"
```

---

## Task 5: Annotations (`tests/sdk/test_annotations.py`)

**Files:**
- Create: `tests/sdk/test_annotations.py`

- [ ] **Step 1: Baseline (verified highlight + sticky-note round-trip)**

```python
import tempfile

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor, Color

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


def _annots(editor):
    return editor.get_page_collection().get_page(1).get_annotation_collection()


class TestBaseline:
    def test_add_markup_and_roundtrip(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                annots = _annots(editor)
                before = annots.get_count()
                hl = annots.add_highlight(72.0, 700.0, 200.0, 20.0, "QA", "important")
                hl.set_color(Color.from_argb(255, 255, 255, 0))
                annots.add_sticky_note(300.0, 700.0, "QA", "Review", "verify")
                editor.save_as(out)
                editor.close()
            with Document.open(out) as doc:
                editor = PdfEditor.edit(doc)
                annots = _annots(editor)
                # each markup spawns a paired Popup -> +4 for 2 markups
                assert annots.get_count() == before + 4
                subtypes = [annots._get_item(i).get_sub_type()
                            for i in range(annots.get_count())]
                assert "Highlight" in subtypes
                assert "Text" in subtypes  # sticky note persists as /Text
                editor.close()
        finally:
            inputs.cleanup(out)
```

- [ ] **Step 2: Run baseline** — `--forked -v` → PASS.

- [ ] **Step 3: Edge cases**

```python
class TestEdgeCases:
    def test_page_index_zero_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                pages.get_page(0)  # 1-based API

    @defect("SDK-011", "get_rect() returns an opaque native handle int, not geometry")
    def test_get_rect_returns_readable_geometry(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(PdfEditor.edit(doc))
            a = annots.add_highlight(72.0, 700.0, 200.0, 20.0, "QA", "x")
            rect = a.get_rect()
            # A usable API returns something with numeric coordinates.
            assert hasattr(rect, "__iter__") or hasattr(rect, "x")

    @defect("SDK-024", "add_highlight accepts negative/zero geometry without validation")
    def test_negative_geometry_rejected(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(PdfEditor.edit(doc))
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                annots.add_highlight(72.0, 700.0, -200.0, 0.0, "QA", "x")

    @defect("SDK-024", "add_square accepts NaN/inf coordinates without validation")
    def test_non_finite_coords_rejected(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(PdfEditor.edit(doc))
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                annots.add_square(float("nan"), float("inf"), 10.0, 10.0, "QA", "x")

    def test_remove_at_out_of_range_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(PdfEditor.edit(doc))
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                annots.remove_at(annots.get_count() + 50)
```

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/pytest tests/sdk/test_annotations.py --forked -v -rxX`

```bash
git add tests/sdk/test_annotations.py
git commit -m "test(sdk): annotation round-trip, geometry-validation, and bounds coverage"
```

---

## Task 6: Forms (`tests/sdk/test_forms.py`)

**Files:**
- Create: `tests/sdk/test_forms.py`

- [ ] **Step 1: Baseline (verified list + fill + detect)**

```python
import tempfile

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


class TestBaseline:
    def test_list_and_fill(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                fields = editor.get_form_field_collection()
                assert fields.get_count() == 15
                target = fields.find_by_full_name("full_name")
                assert target.get_field_type() == 1  # int, not enum (see SDK-...)
                target.set_value("Ada Lovelace")
                assert target.get_value() == "Ada Lovelace"
                editor.save_as(out)
                editor.close()
        finally:
            inputs.cleanup(out)

    def test_detect_adds_fields(self, detection_pdf):
        with Document.open(detection_pdf) as doc:
            editor = PdfEditor.edit(doc)
            fields = editor.get_form_field_collection()
            assert fields.get_count() == 0
            editor.detect_and_add_form_fields()
            assert fields.get_count() > 0  # 13 at default confidence
            editor.close()
```

- [ ] **Step 2: Run baseline** — `--forked -v` → PASS (requires `vision_form` entitlement, present on this key).

- [ ] **Step 3: Edge cases**

```python
class TestEdgeCases:
    @defect("SDK-013", "collection[i] out-of-range raises builtin IndexError, not IndexOutOfBoundsException",
            raises=AssertionError)
    def test_index_out_of_range_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            try:
                _ = fields[999]
                raise AssertionError("expected an exception")
            except nutrient_sdk.NutrientException:
                pass  # desired
            except IndexError:
                raise AssertionError("got builtin IndexError, not NutrientException")

    @defect("SDK-014", "find_by_full_name returns None silently for a missing field")
    def test_missing_field_lookup_raises(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            with pytest.raises(nutrient_sdk.NutrientException):
                fields.find_by_full_name("does_not_exist")

    @defect("SDK-015", "set_value(None) silently accepted on a text field")
    def test_set_value_none_rejected(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            with pytest.raises(nutrient_sdk.NutrientException):
                fields.find_by_full_name("full_name").set_value(None)

    @defect("SDK-016", "invalid radio/combo option accepted without validation")
    def test_invalid_option_rejected(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            with pytest.raises(nutrient_sdk.NutrientException):
                fields.find_by_full_name("account_type").set_value("not_an_option")

    @defect("SDK-017", "field is always base PdfFormField, never the typed subtype")
    def test_field_is_typed_subtype(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            radio = fields.find_by_full_name("account_type")
            assert type(radio).__name__ != "PdfFormField"

    @defect("SDK-018", "confidence_threshold accepts out-of-[0,1] values unvalidated")
    def test_confidence_out_of_range_rejected(self, account_form):
        with Document.open(account_form) as doc:
            frs = doc.get_settings().get_form_recognition_settings()
            with pytest.raises(nutrient_sdk.NutrientException):
                frs.set_confidence_threshold(5.0)
```

- [ ] **Step 4: Run + commit**

Run: `.venv/bin/pytest tests/sdk/test_forms.py --forked -v -rxX`

```bash
git add tests/sdk/test_forms.py
git commit -m "test(sdk): form list/fill/detect baseline + validation/typing defect coverage"
```

---

## Task 7: Signing (`tests/sdk/test_signing.py`)

**Files:**
- Create: `tests/sdk/test_signing.py`

- [ ] **Step 1: Confirm the demo cert path and password**

Run: `ls app/certs/ && grep -ri "password" app/services/signing.py`
Expected: a `.p12` file and the demo password. Use the real values found here in the tests below (the map observed `app/certs/demo-certificate.p12` / password `nutrient-demo` — verify before relying on them).

- [ ] **Step 2: Baseline (verified sign + reopen)**

```python
import os
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, Signature, DigitalSignatureOptions

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect

CERT = str(Path(__file__).resolve().parent.parent.parent / "app" / "certs" / "demo-certificate.p12")
CERT_PASSWORD = "nutrient-demo"  # confirm in Step 1


def _opts():
    o = DigitalSignatureOptions()
    o.set_certificate_path(CERT)
    o.set_certificate_password(CERT_PASSWORD)
    o.set_signer_name("QA")
    return o


class TestBaseline:
    def test_sign_and_reopen(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc, Signature() as signer:
                signer.sign(doc, out, _opts())
            assert Path(out).stat().st_size > 0
            with Document.open(out) as d2:
                assert d2.get_page_count() == 1
        finally:
            inputs.cleanup(out)
```

- [ ] **Step 3: Run baseline** — `--forked -v` → PASS.

- [ ] **Step 4: Edge cases (mix of verified-correct and verified-defect)**

```python
class TestEdgeCases:
    def test_options_none_is_typed(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        with Document.open(account_form) as doc, Signature() as signer:
            with pytest.raises(nutrient_sdk.NutrientArgumentNullException):
                signer.sign(doc, out, None)
        inputs.cleanup(out)

    def test_missing_cert_path_is_typed(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        o = DigitalSignatureOptions()
        o.set_signer_name("QA")
        with Document.open(account_form) as doc, Signature() as signer:
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                signer.sign(doc, out, o)
        inputs.cleanup(out)

    @defect("SDK-022", "nonexistent cert file raises generic SdkException, not FileNotFoundException")
    def test_nonexistent_cert_is_filenotfound(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        o = _opts()
        o.set_certificate_path("/tmp/does-not-exist.p12")
        with Document.open(account_form) as doc, Signature() as signer:
            with pytest.raises(nutrient_sdk.FileNotFoundException):
                signer.sign(doc, out, o)
        inputs.cleanup(out)

    @defect("SDK-020", "set_hash_algorithm(str) raises raw ctypes ArgumentError, not a typed exception")
    def test_hash_algorithm_bad_type_is_typed(self):
        o = DigitalSignatureOptions()
        with pytest.raises(nutrient_sdk.NutrientException):
            o.set_hash_algorithm("SHA256")

    @defect("SDK-021", "Signature use-after-close raises bare ValueError, not InvalidStateException")
    def test_use_after_close_is_typed(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        s = Signature()
        s.close()
        with Document.open(account_form) as doc:
            with pytest.raises(nutrient_sdk.InvalidStateException):
                s.sign(doc, out, _opts())
        inputs.cleanup(out)

    @defect("SDK-023", "sign() with None output path raises InitializationError(1002), not a null-arg exception")
    def test_none_output_path_is_null_arg(self, account_form):
        with Document.open(account_form) as doc, Signature() as signer:
            with pytest.raises(nutrient_sdk.NullOrEmptyParameterException):
                signer.sign(doc, None, _opts())
```

- [ ] **Step 5: Sequential**

```python
class TestSequential:
    def test_sign_then_sign_again(self, account_form):
        # Sign, reopen the signed output, sign again -> must produce a valid PDF.
        out1 = tempfile.mktemp(suffix=".pdf")
        out2 = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc, Signature() as s:
                s.sign(doc, out1, _opts())
            with Document.open(out1) as doc, Signature() as s:
                s.sign(doc, out2, _opts())
            assert Path(out2).read_bytes()[:5].startswith(b"%PDF")
        finally:
            inputs.cleanup(out1, out2)
```

- [ ] **Step 6: Run + commit**

Run: `.venv/bin/pytest tests/sdk/test_signing.py --forked -v -rxX`

```bash
git add tests/sdk/test_signing.py
git commit -m "test(sdk): signing baseline, cert/hash/lifecycle defect coverage, re-sign chain"
```

---

## Task 8: Redaction (`tests/sdk/test_redaction.py`)

**Files:**
- Create: `tests/sdk/test_redaction.py`

- [ ] **Step 1: Baseline (verified apply-redactions burn-in via count delta)**

```python
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor, Color
from nutrient_sdk.pdfsavepreferences import PdfSavePreferences

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


def _annots(doc):
    return PdfEditor.edit(doc).get_page_collection().get_page(1).get_annotation_collection()


class TestBaseline:
    def test_apply_redactions_consumes_annotation(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                annots = editor.get_page_collection().get_page(1).get_annotation_collection()
                before = annots.get_count()
                redact = annots.add_redact(50.0, 50.0, 200.0, 30.0)
                redact.set_interior_color(Color.from_argb(255, 0, 0, 0))
                assert annots.get_count() == before + 1
                doc.settings.pdf_settings.save_preferences = PdfSavePreferences.APPLY_REDACTIONS
                editor.save_as(out)
                editor.close()
            with Document.open(out) as doc2:
                assert _annots(doc2).get_count() == before  # redact consumed
        finally:
            inputs.cleanup(out)
```

- [ ] **Step 2: Run baseline** — `--forked -v` → PASS.

- [ ] **Step 3: The data-leak footgun test (default NONE leaves content)**

```python
class TestFinalizationFootgun:
    @defect("SDK-025", "default NONE save leaves redaction un-applied (content recoverable)")
    def test_default_save_burns_in_content(self, account_form):
        # Without APPLY_REDACTIONS, the redact box is just an annotation; the
        # underlying content is NOT removed. A safe SDK would either burn in or
        # warn. We assert the SAFE behavior (annotation consumed) and expect xfail.
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                annots = editor.get_page_collection().get_page(1).get_annotation_collection()
                before = annots.get_count()
                annots.add_redact(50.0, 50.0, 200.0, 30.0)
                editor.save_as(out)  # no APPLY_REDACTIONS
                editor.close()
            with Document.open(out) as doc2:
                assert _annots(doc2).get_count() == before  # would mean it was applied
        finally:
            inputs.cleanup(out)
```

- [ ] **Step 4: Edge cases**

```python
class TestEdgeCases:
    def test_get_page_zero_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                pages.get_page(0)

    @defect("SDK-024", "add_redact accepts negative geometry without validation")
    def test_negative_redact_geometry_rejected(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(doc)
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                annots.add_redact(50.0, 50.0, -200.0, -30.0)
```

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/pytest tests/sdk/test_redaction.py --forked -v -rxX`

```bash
git add tests/sdk/test_redaction.py
git commit -m "test(sdk): redaction burn-in, finalization footgun, and geometry coverage"
```

---

## Task 9: Vision (`tests/sdk/test_vision.py`)

**Files:**
- Create: `tests/sdk/test_vision.py`

- [ ] **Step 1: Baseline (verified local OCR + ICR, no external key)**

```python
import json
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, Vision, VisionEngine, VisionFeatures

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect
from tests.sdk.conftest import requires_anthropic

LICENSED = VisionFeatures.ALL.value - VisionFeatures.FORM.value


def _extract(path, engine):
    with Document.open(path) as doc:
        vs = doc.get_settings().get_vision_settings()
        vs.set_engine(engine)
        vs.set_features(LICENSED)
        return json.loads(Vision.set(doc).extract_content())["elements"]


class TestBaseline:
    def test_ocr_on_png(self, ocr_png):
        assert len(_extract(ocr_png, VisionEngine.ADAPTIVE_OCR)) > 0

    def test_icr_on_png(self, ocr_png):
        assert len(_extract(ocr_png, VisionEngine.ICR)) > 0
```

- [ ] **Step 2: Run baseline** — `--forked -v` → PASS.

- [ ] **Step 3: Known-defect tests (the two filed bugs + provider edges)**

```python
class TestEdgeCases:
    @defect("SDK-026", "image-only/scanned PDF fails Vision at the InputImage stage")
    def test_scanned_pdf_extracts_or_raises_clean(self, scanned_pdf):
        # A clean SDK either rasterizes internally or raises a CLEAR typed error
        # naming the unsupported page type. Today it raises a truncated
        # VisionException. We assert success; expect xfail until fixed.
        assert len(_extract(scanned_pdf, VisionEngine.ADAPTIVE_OCR)) > 0

    def test_vision_set_none_is_typed(self):
        with pytest.raises(nutrient_sdk.NutrientException):
            Vision.set(None)

    @defect("SDK-027", "out-of-range feature bitmask not rejected")
    def test_bad_features_bitmask_rejected(self, ocr_png):
        with Document.open(ocr_png) as doc:
            vs = doc.get_settings().get_vision_settings()
            vs.set_engine(VisionEngine.ADAPTIVE_OCR)
            vs.set_features(999)
            with pytest.raises(nutrient_sdk.NutrientException):
                Vision.set(doc).extract_content()

    @defect("SDK-028", "extraction.py strips FORM assuming unlicensed, but vision_form IS licensed in 1.0.6")
    def test_form_feature_is_licensed(self, ocr_png):
        # If vision_form is licensed, requesting FORM must NOT raise. xfail
        # asserts the stale opt-out is unnecessary; flips when re-validated.
        with Document.open(ocr_png) as doc:
            vs = doc.get_settings().get_vision_settings()
            vs.set_engine(VisionEngine.ADAPTIVE_OCR)
            vs.set_features(VisionFeatures.FORM.value)
            with pytest.raises(nutrient_sdk.FeatureUnLicensedException):
                Vision.set(doc).extract_content()
```

- [ ] **Step 4: The process-corruption sequential test (the headline SDK bug)**

```python
class TestSequential:
    @defect("SDK-003", "a failed Vision call poisons subsequent good calls in the same process")
    def test_failed_vision_does_not_poison_next(self, scanned_pdf, ocr_png):
        try:
            _extract(scanned_pdf, VisionEngine.ADAPTIVE_OCR)  # known to fail
        except Exception:
            pass
        # In a fresh process this PNG succeeds. After the failure above, it
        # currently fails too (corruption). Assert the SAFE behavior.
        assert len(_extract(ocr_png, VisionEngine.ADAPTIVE_OCR)) > 0

    def test_repeated_ocr_no_segfault(self, ocr_png):
        # Regression guard for the removed _vision_keep_alive SIGSEGV workaround.
        for _ in range(25):
            assert len(_extract(ocr_png, VisionEngine.ADAPTIVE_OCR)) > 0
```

- [ ] **Step 5: Optional Claude-gated describe test**

```python
class TestDescribe:
    @requires_anthropic
    def test_describe_returns_text(self, ocr_png):
        import os
        from nutrient_sdk.vlmprovider import VlmProvider
        with Document.open(ocr_png) as doc:
            s = doc.get_settings()
            s.get_vision_settings().set_provider(VlmProvider.CLAUDE)
            s.get_claude_api_settings().set_api_key(os.environ["ANTHROPIC_API_KEY"])
            text = Vision.set(doc).describe()
        assert isinstance(text, str) and len(text) > 0
```

- [ ] **Step 6: Run + commit**

Run: `.venv/bin/pytest tests/sdk/test_vision.py --forked -v -rxX`
Expected: baseline + `test_repeated_ocr_no_segfault` PASS; the two filed bugs and the corruption test XFAIL. **Critical:** because each test is forked, `test_scanned_pdf...` failing does NOT poison the baseline tests.

```bash
git add tests/sdk/test_vision.py
git commit -m "test(sdk): vision OCR/ICR baseline + image-only/corruption/feature defect coverage"
```

---

## Task 10: Exporters (`tests/sdk/test_exporters.py`)

**Files:**
- Create: `tests/sdk/test_exporters.py`

- [ ] **Step 1: Baseline (verified generic export + convenience methods)**

```python
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import (
    Document, HtmlExporter, PdfExporter, MarkdownExporter, WordExporter,
    ImageExportFormat,
)

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


class TestBaseline:
    @pytest.mark.parametrize("exporter_cls, suffix", [
        (HtmlExporter, ".html"),
        (PdfExporter, ".pdf"),
        (MarkdownExporter, ".md"),
        (WordExporter, ".docx"),
    ])
    def test_generic_export(self, account_form, exporter_cls, suffix):
        out = tempfile.mktemp(suffix=suffix)
        try:
            with Document.open(account_form) as doc:
                with exporter_cls() as exporter:
                    doc.export(out, exporter)
            assert Path(out).stat().st_size > 0
        finally:
            inputs.cleanup(out)
```

- [ ] **Step 2: Run baseline** — `--forked -v` → PASS.

- [ ] **Step 3: Edge cases + missing-binding defects**

```python
class TestEdgeCases:
    @defect("SDK-031", "export() does not guard a closed exporter; sends NULL handle -> native crash")
    def test_export_with_closed_exporter_is_typed(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        exp = PdfExporter()
        exp.close()
        with Document.open(account_form) as doc:
            with pytest.raises((ValueError, nutrient_sdk.NutrientException)):
                doc.export(out, exp)
        inputs.cleanup(out)

    @defect("SDK-002", "None exporter -> InitializationError(1006), not a typed null-arg exception")
    def test_none_exporter_is_typed(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        with Document.open(account_form) as doc:
            with pytest.raises(nutrient_sdk.NutrientArgumentNullException):
                doc.export(out, None)
        inputs.cleanup(out)

    @defect("SDK-030", "ImageExportFormat only exposes TIFF despite docstring claiming PNG/JPEG/TIFF/BMP")
    def test_image_export_formats_available(self):
        names = {m.name for m in ImageExportFormat}
        assert {"PNG", "JPEG", "BMP"}.issubset(names)

    @defect("SDK-029", "no Python API attaches a *Settings object to any exporter")
    def test_exporter_accepts_settings(self):
        exp = HtmlExporter()
        try:
            assert hasattr(exp, "set_settings") or "settings" in dir(exp)
        finally:
            exp.close()
```

- [ ] **Step 4: Process-corruption sequential test**

```python
class TestSequential:
    @defect("SDK-003", "a prior failed export bypasses the use-after-close guard for later calls")
    def test_failed_export_does_not_leak_state(self, account_form):
        # Trigger a failing export, then a clean use-after-close in the same
        # process must still raise the clean Python ValueError, not a native 1006.
        try:
            with Document.open(account_form) as doc:
                doc.export("/nonexistent_dir_xyz/x.pdf", PdfExporter())
        except Exception:
            pass
        doc2 = Document.open(account_form)
        doc2.close()
        with pytest.raises(ValueError):
            doc2.export(tempfile.mktemp(suffix=".pdf"), PdfExporter())
```

- [ ] **Step 5: Run + commit**

Run: `.venv/bin/pytest tests/sdk/test_exporters.py --forked -v -rxX`

```bash
git add tests/sdk/test_exporters.py
git commit -m "test(sdk): exporter matrix baseline + orphaned-settings/format/lifecycle defects"
```

---

## Task 11: Cross-area enterprise workflows (`tests/sdk/test_workflows.py`)

**Files:**
- Create: `tests/sdk/test_workflows.py`

- [ ] **Step 1: The headline multi-step chain**

```python
import tempfile
from pathlib import Path

import pytest
from nutrient_sdk import Document, PdfEditor, Color, Signature, DigitalSignatureOptions

from tests.sdk._support import inputs
from tests.sdk.test_signing import CERT, CERT_PASSWORD


class TestEnterpriseChains:
    def test_fill_annotate_sign_reopen(self, account_form):
        """A realistic pipeline: open -> fill a field -> add a highlight ->
        save -> sign the saved doc -> reopen the signed output and verify."""
        filled = tempfile.mktemp(suffix=".pdf")
        signed = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                editor.get_form_field_collection().find_by_full_name("full_name").set_value("Ada")
                annots = editor.get_page_collection().get_page(1).get_annotation_collection()
                hl = annots.add_highlight(72.0, 700.0, 200.0, 20.0, "QA", "reviewed")
                hl.set_color(Color.from_argb(255, 255, 255, 0))
                editor.save_as(filled)
                editor.close()

            o = DigitalSignatureOptions()
            o.set_certificate_path(CERT)
            o.set_certificate_password(CERT_PASSWORD)
            o.set_signer_name("QA")
            with Document.open(filled) as doc, Signature() as signer:
                signer.sign(doc, signed, o)

            with Document.open(signed) as doc:
                editor = PdfEditor.edit(doc)
                assert editor.get_form_field_collection().find_by_full_name("full_name").get_value() == "Ada"
                editor.close()
        finally:
            inputs.cleanup(filled, signed)

    def test_edit_then_convert(self, account_form):
        """Edit pages, save, then convert the edited PDF to Markdown."""
        edited = tempfile.mktemp(suffix=".pdf")
        md = tempfile.mktemp(suffix=".md")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                editor.get_page_collection().add(width=200.0, height=300.0)
                editor.save_as(edited)
                editor.close()
            with Document.open(edited) as doc:
                assert PdfEditor.edit(doc).get_page_collection().get_count() == 2
            with Document.open(edited) as doc:
                doc.export_as_markdown(md)
            assert Path(md).stat().st_size > 0
        finally:
            inputs.cleanup(edited, md)
```

- [ ] **Step 2: Repeated full-pipeline stress**

```python
class TestPipelineStress:
    def test_repeated_pipeline_no_leak(self, account_form):
        for _ in range(10):
            out = tempfile.mktemp(suffix=".pdf")
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                editor.get_form_field_collection().find_by_full_name("full_name").set_value("X")
                editor.save_as(out)
                editor.close()
            with Document.open(out) as doc:
                assert doc.get_page_count() == 1
            inputs.cleanup(out)
```

- [ ] **Step 3: Run + commit**

Run: `.venv/bin/pytest tests/sdk/test_workflows.py --forked -v -rxX`

```bash
git add tests/sdk/test_workflows.py
git commit -m "test(sdk): cross-area enterprise pipeline + repeated-pipeline stress coverage"
```

---

## Task 12: Full-suite run + triage pass

**Files:**
- Modify: `docs/sdk-feedback/DEFECTS.md` (reconcile with actual XFAIL/XPASS results)
- Modify: `HANDOFF.md` (link the new suite + registry)

- [ ] **Step 1: Run the whole suite**

Run: `make test-sdk`
Expected: a clean run where every assertion either PASSES (correct behavior) or XFAILs (known defect). Capture the `-rxX` summary.

- [ ] **Step 2: Reconcile the registry**

For each XFAIL, confirm a matching `DEFECTS.md` row. For any test that unexpectedly **passed** where a defect was predicted (XPASS under strict → red), investigate: either the SDK behaves better than the map suggested (remove the marker, mark the row `fixed`/`not-reproduced`) or the assertion is wrong (fix it). For any **new** red failure, add a `DEFECTS.md` row and a `defect()` marker.

- [ ] **Step 3: Draft bug-report stubs for high-severity findings**

For each `severity = high|critical` row not already `filed`, create a stub in `docs/sdk-feedback/bug-reports/` following the existing format (repro snippet from the test, expected vs actual, SDK version). At minimum: SDK-003 (corruption), SDK-007 (rotation gap), SDK-011 (opaque rect), SDK-017 (form subtype), SDK-029 (orphaned exporter settings).

- [ ] **Step 4: Update HANDOFF.md**

Add a section pointing to `tests/sdk/`, `make test-sdk`, and `docs/sdk-feedback/DEFECTS.md`, noting the suite is the new entry point for SDK QA.

- [ ] **Step 5: Final commit**

```bash
git add docs/sdk-feedback HANDOFF.md
git commit -m "docs(sdk): reconcile defect registry with suite results + handoff pointers"
```

---

## Self-review notes

- **Spec coverage:** All nine areas from the spec have a task (Tasks 2–10), plus cross-area workflows (Task 11). Isolation/`pytest-forked` (Task 1), defect log + `defect()` marker (Task 1), and the `make test-sdk` target (Task 1) are all covered. The three test classes per area are present.
- **Fork-safety gating:** Task 1 Steps 2/5/6 are the spike — they run before any area work and prove isolation both works and is necessary. If Step 6 shows corruption no longer reproduces in-process, the note instructs keeping `--forked` for SIGSEGV containment anyway.
- **Cert assumptions:** Task 7 Step 1 verifies the demo cert path/password before relying on them (the map *observed* them but they must be confirmed).
- **Fixture assumption:** Task 1 notes `usenix-paper.pdf` should be verified present (one agent mis-reported it missing; the dir listing shows it exists).
- **xfail honesty:** Every `defect()` is `strict=True`, so a fixed SDK turns the suite red — exactly the regression signal the user wants. New failures (no marker) fail loudly.
