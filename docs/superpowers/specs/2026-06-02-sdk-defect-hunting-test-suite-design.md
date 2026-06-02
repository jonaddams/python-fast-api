# SDK Defect-Hunting Test Suite — Design

Date: 2026-06-02
Status: Approved (brainstorming) → pending implementation plan

## Problem

The Nutrient Python SDK (`nutrient-sdk==1.0.6`) is new, and this project has
already surfaced several real defects (process-wide Vision state corruption,
`Vision.set()` failing on image-only PDFs, multiple no-op settings). The concern
is that the product's QA is weak and that customers will hit issues before we do.

We want a comprehensive, rigorous test suite that exercises the SDK the way an
enterprise integration would: calling APIs repeatedly in sequence, chaining
operations across a document's lifecycle, and pushing edge-case, null, and
malformed inputs — so that defects are found here, with clean repros, before they
reach customers.

## Goals

- Systematically cover the **full SDK surface**, not just what the demo wraps.
- Drive the **SDK directly** (`import nutrient_sdk`), bypassing FastAPI and
  `app.services`, so findings are unambiguously SDK defects with minimal-noise
  repros suitable for handing to the SDK team.
- Treat the suite as both a **regression net** and a **living defect report**:
  tests assert *correct* behavior; known defects are marked `xfail` and linked to
  a defect registry, so the suite stays green while every known bug stays visible
  and an SDK fix is detected automatically.

## Non-goals (this pass)

- Property-based / fuzz testing with `hypothesis` — deferred. May be added later
  as a *targeted* slice for cheap, deterministic, in-process surfaces (settings
  validation, filename/argument parsing) only. Live-VLM and native-inference
  paths stay on hand-written cases regardless.
- Testing the FastAPI endpoints (the existing `tests/` already does HTTP-level
  integration).
- Performance/throughput benchmarking.

## Approach

Approach A from brainstorming: a layered, process-isolated defect-hunting suite,
organized by SDK capability area, with per-test process isolation and an `xfail`
+ defect-log convention.

### Layout

A new top-level `tests/sdk/` package, kept separate from the functional `tests/`.

```
tests/sdk/
  conftest.py              # fork mode, per-process SDK init guard, defect markers, shared fixtures
  README.md                # how to read xfail/xpass output; how to promote a finding to a bug report
  _support/
    inputs.py              # bad-input generators (empty, truncated, wrong-ext, huge, unicode-name)
    workflows.py           # reusable multi-step chains
    assertions.py          # helpers: assert_raises_sdk_error, assert_clean_failure, etc.
  test_document.py         # open/save/export, lifecycle, double-close, use-after-close
  test_conversion.py       # Office<->PDF, MD->PDF, PDF->HTML/Word/Image/Spreadsheet/Presentation/SVG
  test_editor.py           # PdfEditor / WordEditor primitives, page operations
  test_annotations.py      # the Pdf*Annotation hierarchy: create / round-trip / save
  test_forms.py            # list / fill / detect; field-type subtypes
  test_signing.py          # Signature API, hash algorithms, appearance, timestamp config
  test_redaction.py        # redact annotation -> apply -> verify content gone
  test_vision.py           # OCR / ICR / VLM / describe / tables / markdown / fields
  test_exporters.py        # Html/Markdown/Word/Image/Spreadsheet/Presentation/Svg settings matrix
  test_workflows.py        # cross-area enterprise sequences (the headline suite)
```

Capability areas trace directly to the SDK's top-level exports (Document
lifecycle, the eight exporters, the annotation and form-field hierarchies,
Signature, Redaction, Vision, Conversion). "Full surface" is therefore concrete
and auditable.

### Test classes (per area file)

Every area file carries the same three classes so coverage is auditable:

**`TestBaseline`** — one or two happy-path calls per API on good input. Proves the
API works at all, so an edge-case failure is unambiguously about the edge.

**`TestEdgeCases`** — the abuse matrix, applied per input-taking API:
- **Null/empty**: `None` for a required arg, empty `bytes`, empty string,
  zero-page document.
- **Malformed**: truncated file (first ~100 bytes of a PDF), wrong magic bytes,
  PNG renamed `.pdf`, a `.docx` that is actually plain text, random bytes.
- **Boundary**: huge synthetic input, 0/negative/over-max numeric settings (DPI,
  confidence, out-of-range page indices), empty field lists.
- **Identity/encoding**: unicode and very long filenames, path-traversal-looking
  names, names with spaces.
- **Lifecycle misuse**: double-close, use-after-close, save-without-open, export
  to an unwritable path.

Each case asserts the SDK fails **cleanly** — a typed exception from its own
hierarchy (`NullOrEmptyParameterException`, `InvalidArgumentException`,
`InvalidStateException`, `NutrientArgumentNullException`, etc.) — **not** a
SIGSEGV, a bare `Exception`, silent wrong output, or process poisoning. That gap
is the defect.

**`TestSequential`** — enterprise workflows:
- **Multi-step chains**: open -> edit pages -> fill form -> sign -> save ->
  reopen -> extract -> redact -> save, asserting integrity at each handoff.
- **Loop stress**: the same operation N times in one process (e.g. 50x Vision,
  50x open/close) to surface state leaks, handle exhaustion, memory growth, and
  the documented Vision-corruption-after-failure pattern.
- **Interleaving**: deliberately run a known-bad call, then a good call, and
  assert the good one still succeeds — directly targets the process-wide
  corruption defect.

### Isolation & crash containment

This is load-bearing for this SDK.

- **Per-test process isolation via `pytest-forked`** (new dev dependency). Each
  test runs in a forked child: the Vision process-corruption bug cannot leak into
  the next test, and a SIGSEGV kills only that child and is reported as a failure
  rather than aborting the whole run. Applied only within `tests/sdk/` (via
  `--forked` scoped to that package), not the existing functional `tests/`.
- **SIGSEGV is a first-class signal.** `faulthandler` stays disabled (existing
  constraint — the native lib raises SIGSEGV internally). A child that dies on a
  signal surfaces as a failed test; in `TestEdgeCases` a crash *is* the finding
  and is marked `xfail` with a defect ID and a one-line repro. The fork boundary
  is what lets us record "this input segfaults" without aborting the session.
- **Per-process SDK init.** `conftest.py` registers the license once per child
  (the SDK re-initializes per process under fork). Before committing to
  `--forked`, a short spike confirms the init path is fork-safe; fallback is a
  subprocess-per-case harness if fork interacts badly with the native runtime.

### Defect log & xfail convention

- **Registry**: `docs/sdk-feedback/DEFECTS.md` — a numbered table (ID, area,
  one-line symptom, severity, status open/filed/fixed, link to a `bug-reports/`
  file if filed). Seeded from the defects already documented in `HANDOFF.md`:
  image-only-PDF failure, process-wide corruption, `KEY_VALUE_REGION` no-op, ICR
  confidence-threshold no-ops, `AiAugmenter` no-ops, single-page pre-render limit.
- **Marker helper**: `defect(id, reason)` wrapping
  `pytest.mark.xfail(strict=True, reason=f"DEFECT-{id}: {reason}")`. `strict=True`
  means a fixed bug `xpass`es and turns the suite **red** until the marker is
  removed — the prompt to update the log. New, undocumented failures fail loudly
  (no marker exists yet).
- **Docs**: `tests/sdk/README.md` explains how to read the xfail/xpass summary
  and how to promote a finding into a `docs/sdk-feedback/bug-reports/` filing.

### Running

- New Makefile target `make test-sdk` runs `tests/sdk/` with `--forked` and prints
  the xfail/xpass summary. The existing `make test` is unchanged.
- Live-VLM-dependent Vision tests reuse the existing skip markers
  (`requires_anthropic`, `requires_openai`) so the suite stays runnable without
  keys; non-VLM areas (Document, Conversion, Editor, Forms, Signing, Redaction,
  Annotations, Exporters) need no external services.

## Error handling

- Helper `assert_clean_failure(callable, *, allowed_exceptions)` centralizes the
  "failed cleanly vs crashed/poisoned/silently-wrong" judgement, so every edge
  case states explicitly what an acceptable failure looks like.
- A crash (SIGSEGV / child died on signal) is never swallowed: it is either an
  expected `xfail` finding or a loud failure.

## Testing (of the suite itself)

- `TestBaseline` in each area doubles as the smoke test that the suite's own
  fixtures and SDK init are working.
- The fork-safety spike is the gating check before the rest of the suite is built.

## Build sequence (for the implementation plan)

1. Spike: confirm `pytest-forked` + per-process SDK license init is fork-safe.
2. Scaffolding: `tests/sdk/conftest.py`, `_support/` helpers, `defect()` marker,
   `DEFECTS.md` seeded, Makefile target, `tests/sdk/README.md`.
3. Non-VLM areas first (no external deps): Document, Conversion, Editor,
   Annotations, Forms, Signing, Redaction, Exporters — baseline -> edge -> sequential.
4. Vision area (gated on keys): OCR/ICR/VLM/describe/tables/markdown/fields.
5. Cross-area `test_workflows.py`.
6. Triage pass: record every new finding in `DEFECTS.md`, mark `xfail`, draft
   bug-report stubs for the high-severity ones.
