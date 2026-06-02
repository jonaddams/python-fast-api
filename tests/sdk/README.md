# SDK Defect-Hunting Test Suite

Tests in this directory drive the Nutrient Python SDK **directly** (no FastAPI) to find, document, and track SDK-level defects.

## Running

```bash
make test-sdk
# Equivalent to:
.venv/bin/pytest tests/sdk/ --forked -v -rxX
```

Tests MUST be run with `--forked`. Each test runs in a separate child process via `pytest-forked`. This is not optional — see *Fork isolation* below.

## How xfail / defect markers work

- An `xfail` test documents a **known SDK defect**. It is expected to fail.
- A `strict` `XPASS` (unexpected pass) turns the suite **red** — this means the SDK fixed the bug. When that happens: remove the `defect()` marker and update `../../docs/sdk-feedback/DEFECTS.md` to mark the row `fixed`.
- A new **red failure** that is NOT marked `xfail` is a freshly-found defect. Add a row to `DEFECTS.md` and wrap the test with `defect("SDK-NNN", "...")`.

The `defect()` helper lives in `_support/markers.py` and is a thin wrapper around `pytest.mark.xfail(strict=True, ...)`.

The full defect registry is at: [`../../docs/sdk-feedback/DEFECTS.md`](../../docs/sdk-feedback/DEFECTS.md)

## Fork isolation — why it is load-bearing

The Nutrient Python SDK has a **process-wide native state corruption bug** (SDK-003): once any Vision/native call fails, every subsequent call in the same Python process fails with the same error, regardless of input.

**Observed result (Step 6, 2026-06-02):** When `test_fork_isolation_contains_vision_corruption` (which triggers the image-only-PDF Vision defect, SDK-026) was run *before* `test_smoke_ocr_on_png_succeeds` in the **same process** (no `--forked`), the OCR test **FAILED** with:

```
nutrient_sdk.visionexception.VisionException: 1 context(s) failed:
VisionDocumentGraphExtraction: Vision extraction failed for page 1: ...
InputImage: imageFilePath parameter is required (Error Code: 3024) [Source: Set]
```

Under `--forked`, each test runs in its own child process. The corruption dies with the child and cannot poison any other test. **Both tests PASS.**

This confirms `--forked` is load-bearing: without it, test ordering determines which tests pass, making the suite non-deterministic and unreliable. Even if SDK-003 is eventually fixed, `--forked` is kept for **SIGSEGV containment** — the native library raises SIGSEGV internally during some operations (see `faulthandler` note in `pyproject.toml`), which would otherwise abort the entire pytest process.

## Directory layout

```
tests/sdk/
├── conftest.py          # Per-child license registration + shared fixtures
├── test_smoke.py        # Fork-safety spike (gate test — must pass first)
├── _support/
│   ├── inputs.py        # Malformed/edge-case input generators
│   ├── assertions.py    # SDK error-type helpers
│   └── markers.py       # defect() xfail wrapper
└── README.md            # This file
```
