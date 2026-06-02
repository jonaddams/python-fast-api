# Handoff — Nutrient Python SDK demo

Last updated: 2026-06-01 · Session ran 2026-05-28 through 2026-06-01.

This document is the entry point for any future session picking up work on this repo. It covers what's here, what's been done recently, where the bodies are buried, and what's pending external action.

---

## SDK defect-hunting test suite

Branch `sdk-defect-hunting-tests` (merged or rebased from `extraction-demos-spec`) adds a
comprehensive defect-hunting suite at `tests/sdk/`. Run it with:

```bash
make test-sdk   # = .venv/bin/pytest tests/sdk/ --forked -v -rxX
```

**Result: 39 passed / 39 xfailed / 0 failed / 0 xpassed** (~34s on Apple M4).

Key facts for whoever picks this up:

- **Registry:** `docs/sdk-feedback/DEFECTS.md` — 35 catalogued defects (SDK-001..SDK-035).
  31 confirmed by automated xfail tests; 4 documented-only (SDK-005, SDK-012, SDK-019, SDK-033).
- **`--forked` is required.** SDK-003 (process-wide native state corruption after a failed
  Vision call or exporter call) and the SDK-034/035 macOS fork-safety class make it unsafe
  to run these tests sequentially in a single process. `pytest-forked` gives each test its
  own process. Remove `--forked` only if you fully understand the corruption risk.
- **Fork-safety (SDK-034/035):** Once `nutrient_sdk` is loaded, calling `sign()` or
  `Vision.describe()` in a `fork()`ed child aborts (SIGABRT/SIGSEGV) on macOS due to
  Security.framework and VLM-path fork hostility. The workaround is `subprocess.run()` in a
  freshly spawned interpreter; see `tests/sdk/test_signing.py::_run_in_subprocess`.
- **Bug report stubs:** 6 new JIRA-ready files under `docs/sdk-feedback/bug-reports/` for
  the confirmed high-severity defects: SDK-002, SDK-007, SDK-011, SDK-017, SDK-025, SDK-029.
  The two critical reports (SDK-003, SDK-026) were filed previously.

### Shipped-code bugs found by the suite (NOT SDK defects — need separate fixing)

These are bugs in **this repo's** application code uncovered during the defect hunt:

1. **`app/services/redaction.py` line ~24: `pages.get_item()` does not exist.**
   The correct call is `pages.get_page(n)` (1-based index). The redaction endpoint
   (`POST /api/redaction/redact`) is broken and will 500 on any request. No existing
   integration test covers this endpoint. Fix: replace `pages.get_item(page_num)` with
   `pages.get_page(page_num)` (and verify the page number is 1-based, not 0-based).

---

## Project at a glance

Two repos, paired:

| Repo | Path | Role |
|---|---|---|
| **`python-fast-api`** (this repo) | `/Users/jonaddamsnutrient/SE/code/python-fast-api` | FastAPI backend wrapping the Nutrient Python SDK |
| **`nutrient-sdk-samples`** | `/Users/jonaddamsnutrient/SE/code/nutrient-sdk-samples` | Next.js frontend demos that call the backend |

**SDK pins (both packages):** `nutrient-sdk==1.0.6`, `nutrient-sdk-native==1.0.6`. Set in `pyproject.toml`.
**Python:** 3.12 (`python3.12 -m venv .venv` then `make install`).
**License:** `NUTRIENT_LICENSE_KEY` in `.env`. Regenerated 2026-05-28 to include `vision_form` (required for form-field detection). Don't break this — getting a key with the right entitlements took an actual round trip.

## Running locally

```bash
make dev        # uvicorn :8080 with --reload
make test       # ~19 passing, 2 skipped, ~3–4 min (many tests make live VLM/Claude calls)
make install    # re-sync editable install
```

For the frontend, in the companion repo:

```bash
NEXT_PUBLIC_PYTHON_SDK_API_URL=http://localhost:8080 pnpm dev
```

Open `http://localhost:3000/python-sdk` for the index.

---

## What the demo currently shows

The Python SDK section of the frontend has these demo pages, all powered by this backend:

| Demo path | Backend endpoint | What it shows |
|---|---|---|
| `/python-sdk/ocr-extraction` | `POST /api/extraction/ocr` | Adaptive OCR on a scanned invoice PDF and on the Nutrient guide's multi-language image |
| `/python-sdk/icr-extraction` | `POST /api/extraction/icr` | ICR on the Nutrient guide's multi-language image and on a hand-printed employment app |
| `/python-sdk/vlm-extraction` | `POST /api/extraction/vlm?provider=claude` | VLM-enhanced ICR live against Claude on an invoice |
| `/python-sdk/vlm-transcription` | `POST /api/extraction/describe` | Custom-prompt transcription via `Vision.describe()` (`level=standard\|detailed`) |
| `/python-sdk/table-extraction *(frontend pending)*` | `POST /api/extraction/tables?provider=claude` | Structured table extraction — returns per-cell row/column/span/confidence |
| `/python-sdk/markdown-extraction *(frontend pending)*` | `POST /api/extraction/markdown?provider=claude` | Document → clean Markdown for RAG/LLM ingestion |
| `/python-sdk/field-extraction *(frontend pending)*` | `POST /api/extraction/fields?provider=claude` | Key-value extraction: native `KEY_VALUE_REGION` regions + schema-driven JSON via `Vision.describe()` |
| `/python-sdk/form-detection` | `POST /api/forms/detect` | Form-field detection on IRS F940 with a confidence slider |
| `/python-sdk/form-fill` | `POST /api/forms/list-fields` + `POST /api/forms/fill-fields` | (existed before this session) |
| `/python-sdk/digital-signature` | `POST /api/signing/sign-demo` | (existed before this session) |
| `/python-sdk/redaction`, `word-template`, `office-to-pdf`, `md-to-pdf`, `pdf-to-html`, `pdf-to-office` | various | (existed before this session) |

> **Note:** rows marked *(frontend pending)* have working backend endpoints but no frontend page yet — those pages are the next planned slice in the companion `nutrient-sdk-samples` repo.

---

## Major work that landed this session

In rough chronological order:

1. **SDK 1.0.6 migration.** Broke a stack of APIs (`VisionEngine.OCR` → `ADAPTIVE_OCR`, `FORM` license bit, VLM endpoint, `PdfSigner` removal). All caught and fixed; `tests/` covers the regressions.
2. **Form-field detection feature.** `POST /api/forms/detect` with `?confidence=` query param, plus a frontend demo page (IRS F940 with a slider).
3. **ICR engine quality investigation.** 18 real-world handwriting samples. Headline: ICR is unusable on cursive but works on clean print in forms. Claude transcribes the same cursive samples cleanly. Full writeup at `docs/sdk-feedback/2026-05-28-icr-engine-quality.md`.
4. **Claude-vs-ICR comparison artifacts.** Markdown + standalone HTML at `docs/sdk-feedback/claude-vs-icr-comparison/`. The HTML (`index.html`) is the stakeholder-presentation version.
5. **ICR/OCR/VLM/Transcription demo pages.** Four new pages with consistent layout.
6. **Discovered `Vision.describe()` honors a custom `standard_prompt`.** The SDK already has a high-quality transcription path; it just isn't documented as one. Exposed via `POST /api/extraction/describe`.
7. **Discovered `VlmProvider.CUSTOM` is fully functional.** Eleven configurable knobs (`api_endpoint`, `api_key`, `model`, `temperature`, `max_tokens`, `stream`, `batch_size`, `max_concurrency`, `classification_strategy`, `send_full_page_reference`, `system_prompt`). Real differentiator.
8. **Discovered `VLM_ENHANCED_ICR` works with `VlmProvider.CLAUDE`.** No localhost:1234 LM Studio needed; pass `?provider=claude` and the engine routes through Anthropic. Unblocked the VLM Extraction demo to do live calls.
9. **Removed the `_vision_keep_alive` workaround.** Stress-tested 50× OCR + 50× ICR on 1.0.6 — no SIGSEGV. The unbounded list growth from 1.0.2 era is gone.
10. **Filed two JIRA-ready bug reports** under `docs/sdk-feedback/bug-reports/` (see the dedicated section below).

PRs from this session (all merged): python-fast-api #1–#11, nutrient-sdk-samples #13–#22.

---

## Key files for the next session

### Code

| File | Why it matters |
|---|---|
| `app/services/extraction.py` | All Vision API wrappers. Includes the **PDF pre-render workaround** (lines 86–101) — see Known Bugs below. |
| `app/services/forms.py` | Form list/fill/detect. The `detect_fields()` function accepts an optional `confidence_threshold`. |
| `app/services/signing.py` | Uses the new `Signature` API (post-1.0.6 rename from `PdfSigner`). |
| `app/routers/extraction.py` | `/ocr`, `/icr`, `/vlm` (with `?provider=`), `/describe` (with `prompt`, `provider`, `level`), `/tables`, `/markdown`, `/fields`. |
| `tests/test_extraction.py` | Tests covering all extraction paths including the image-only-PDF regression, new VLM endpoints, and OpenAI parity (skipped when key absent). |
| `tests/test_forms_detect.py` | Confidence threshold sweep tests. |
| `Makefile` | `make test`, `make dev`, `make install`. |
| `pyproject.toml` | SDK pins + `addopts = "-p no:faulthandler"` (don't remove without re-validating; the SDK uses SIGSEGV internally). |

### Docs

| Folder | What's there |
|---|---|
| `docs/sdk-feedback/` | All SDK quality writeups. The big one is `2026-05-28-icr-engine-quality.md`. |
| `docs/sdk-feedback/bug-reports/` | JIRA-ready defect writeups. See section below. |
| `docs/sdk-feedback/claude-vs-icr-comparison/` | The stakeholder presentation. `index.html` is the polished version. |
| `docs/superpowers/plans/` | Implementation plans (all executed). |
| `docs/superpowers/specs/` | Design docs. |

### External

- `recipes/` (gitignored; locally in working tree) — 18 handwriting samples from Reddit corpora used in the ICR investigation. Not redistributable. The ICR transcripts are at `recipes/icr-results/*.txt`.
- The companion repo (`nutrient-sdk-samples`) has its own `README.md` with setup instructions for both Python and .NET SDK demos.

---

## Known SDK issues — read before debugging

### Filed as bugs (in `docs/sdk-feedback/bug-reports/`)

1. **`Vision.set()` fails on image-only PDFs.** Scanned invoices throw `imageFilePath parameter is required`. Workaround: pre-render the PDF to PNG (already implemented in `_extract_with_engine`). Don't try to use `Vision` on a scanned PDF without that pre-render.
2. **Vision SDK has process-wide state corruption after any failed call.** Once one Vision call fails on a bad input, every subsequent Vision call in the same Python process fails with the same exception. This is why we always pre-render PDFs *before* the first Vision call — once you've triggered the bug, the process is poisoned for its lifetime.

### Not filed but worth knowing

3. **Documented confidence thresholds on ICR are no-ops.** `SegmenterSettings.confidence_threshold` and `WordsDetectionSettings.confidence_threshold` accept values but don't change the output. Documented in the engine-quality doc; recommendation #5 there is to file separately.
4. **`AiAugmenter.enable_*` flags are all no-ops on ICR.** Same pattern — they accept the setting but the ICR pipeline ignores them. All 5 toggles produce byte-identical output.
5. **ICR confidence scores are uncorrelated with output quality.** Don't build threshold-based auto-accept logic on ICR confidence.
6. **The form-detection engine returns generic `PdfFormField` instances, not subtypes.** No way to distinguish detected text fields from detected checkboxes from the output alone.
7. **The PDF pre-render workaround only handles the first page** (`Document.export_as_image()` writes one image). Multi-page scanned PDFs lose pages 2+. Acceptable for the current demo; a real fix needs page iteration.
8. **`VisionFeatures.KEY_VALUE_REGION` appears to be a no-op on tested documents.** Running it on `ocr-invoice.pdf` via Claude returned 20 elements, but none were tagged as key/value regions — `nativeRegions` came back `[]`. The feature is licensed (shows in the SDK banner) but produces no key-value-tagged elements. This is why `/api/extraction/fields` pairs it with a schema-driven `describe()` prompt, which does return the requested fields cleanly. Consistent with the pattern of other no-op Vision features already documented in the engine-quality doc. Candidate for a separate SDK-feedback filing.

---

## Pending external action — things blocked on Daisy

| Item | Status |
|---|---|
| **File the two JIRA tickets** | Bug reports ready at `docs/sdk-feedback/bug-reports/`. User said they'd file. |
| **OpenAI provider parity tests** (tables, fields, markdown) | Gated parity tests exist in `tests/test_extraction.py` and currently SKIP because the `OPENAI_API_KEY` in `.env` is invalid (returns "VLM endpoint ... properly configured" SDK error). Once a valid key is in `.env`, the tests will run automatically and verify response-shape parity. The helper `skip_if_openai_unavailable` keeps the suite green until then. |
| **Manager review of the comparison HTML** | The stakeholder review of `docs/sdk-feedback/claude-vs-icr-comparison/index.html` — outcome unknown. |
| **(Maybe) refresh `tests/fixtures/`** with newer sample images | The Reddit-corpus images in `recipes/` are not committed because they're not redistributable. If someone needs to rerun the ICR investigation locally, the corpus needs to be re-fetched manually. |

---

## Things explicitly out of scope / decided against

- **Multi-page PDF support in the pre-render workaround.** Single-page only for now; documented in the bug report.
- **`Vision.transcribe()` API as a separate ask.** Downgraded after discovering the custom-prompt path works — now framed as a documentation gap, not a missing feature.
- **Replacing ICR with VLM in the demo entirely.** The ICR Extraction page stays as a sibling to VLM Transcription — they tell different stories. ICR has genuine value on print-handwriting in forms.
- **OpenAI provider parity ICR comparison** — set aside because Anthropic provider is sufficient for the comparison story; OpenAI key was broken.
- **Benchmarking against Google Document AI / AWS Textract / Azure Document Intelligence.** Recommended in the engineering-feedback section of the comparison doc but not executed in this session.

---

## How to resume quickly

If picking up cold:

1. `cd /Users/jonaddamsnutrient/SE/code/python-fast-api && make test` — confirm baseline (should be ~19 passing, 2 skipped in ~3–4 min; skips are OpenAI parity tests blocked on invalid key).
2. Read `docs/sdk-feedback/bug-reports/README.md` — the two open SDK bugs are the most important context.
3. Skim `docs/sdk-feedback/2026-05-28-icr-engine-quality.md` to refresh on the ICR/VLM story.
4. `git log --oneline -20` — recent PR history is informative.
5. Check `.env` is intact (NUTRIENT_LICENSE_KEY with `vision_form` entitlement, ANTHROPIC_API_KEY, OPENAI_API_KEY if available).

If there's a specific question about why some setting or workaround is there, search the engine-quality doc first — most of the surprises are documented.
