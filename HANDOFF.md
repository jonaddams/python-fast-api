# Handoff — Nutrient Python SDK demo

Last updated: 2026-06-03 · Covers sessions 2026-05-28 through 2026-06-03.

This document is the entry point for any future session picking up work on this repo. It covers what's here, what's been done recently, where the bodies are buried, and what's pending external action.

---

## SDK defect-hunting test suite

PR #14 (merged 2026-06-02) added a comprehensive defect-hunting suite at `tests/sdk/`. Run it with:

```bash
make test-sdk   # = .venv/bin/pytest tests/sdk/ --forked -v -rxX
```

**Result: 38 passed / 38 xfailed / 2 skipped / 0 failed / 0 xpassed** (~35s on Apple M4).

Key facts for whoever picks this up:

- **Registry:** `docs/sdk-feedback/DEFECTS.md` — 35 catalogued defects (SDK-001..SDK-036,
  excluding SDK-028 which was reclassified as code-cleanup and fixed via PR #17).
- **`--forked` is required.** SDK-003 (process-wide native state corruption after a failed
  Vision call or exporter call) and the SDK-034/035 macOS fork-safety class make it unsafe
  to run these tests sequentially in a single process. `pytest-forked` gives each test its
  own process. Remove `--forked` only if you fully understand the corruption risk.
- **Fork-safety (SDK-034/035):** Once `nutrient_sdk` is loaded, calling `sign()` or
  `Vision.describe()` in a `fork()`ed child aborts (SIGABRT/SIGSEGV) on macOS due to
  Security.framework and VLM-path fork hostility. The workaround is `subprocess.run()` in a
  freshly spawned interpreter; see `tests/sdk/test_signing.py::_run_in_subprocess`.
- **Fork-crash tests are gated (PR #18).** The two SDK-034/035 reproductions crash a child
  process by design, which pops a macOS "Python quit unexpectedly" dialog on every run.
  They skip by default; run `SDK_FORK_CRASH_TESTS=1 make test-sdk` for the full 39/39
  coverage (do this after any SDK version bump).
- **Bug report stubs:** 6 JIRA-ready files under `docs/sdk-feedback/bug-reports/` for
  the confirmed high-severity defects: SDK-002, SDK-007, SDK-011, SDK-017, SDK-025, SDK-029.
  The two critical reports (SDK-003, SDK-026) were filed previously. **None of the 6 stubs
  have been filed yet.**

### Shipped-code bugs found by the suite — BOTH FIXED (PR #17, merged 2026-06-03)

1. **`app/services/redaction.py` called the non-existent `pages.get_item()`.** Fixed to
   `get_page(page_index + 1)` — the frontend sends 0-based page indices, the SDK's
   `get_page()` is 1-based. The redaction endpoint now has its first integration test
   (`tests/test_redaction.py`).
2. **`app/services/extraction.py` stripped `VisionFeatures.FORM` as if unlicensed** (SDK-028),
   but the license key regenerated 2026-05-28 includes `vision_form`. The opt-out is gone;
   `_LICENSED_VISION_FEATURES` is the full set, pinned by
   `tests/test_extraction.py::test_licensed_vision_features_is_full_set`.

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
**LLM keys:** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are both valid in `.env` and on the deployed Railway service (as of 2026-06-02). `.env.example` lists all recognized variables.

## Running locally

```bash
make dev        # uvicorn :8080 with --reload
make test       # 24 passing, 0 skipped, ~3 min (many tests make live VLM/Claude/OpenAI calls)
make test-sdk   # SDK defect suite, 38 passed / 38 xfailed / 2 skipped, ~35s
make install    # re-sync editable install
```

For the frontend, in the companion repo:

```bash
NEXT_PUBLIC_PYTHON_SDK_API_URL=http://localhost:8080 pnpm dev
```

Open `http://localhost:3000/python-sdk` for the index.

---

## What the demo currently shows

The Python SDK section of the frontend has these demo pages, all powered by this backend, all live:

| Demo path | Backend endpoint | What it shows |
|---|---|---|
| `/python-sdk/ocr-extraction` | `POST /api/extraction/ocr` | Adaptive OCR on a scanned invoice PDF and on the Nutrient guide's multi-language image |
| `/python-sdk/icr-extraction` | `POST /api/extraction/icr` | ICR on the Nutrient guide's multi-language image and on a hand-printed employment app |
| `/python-sdk/vlm-extraction` | `POST /api/extraction/vlm?provider=claude` | VLM-enhanced ICR live against Claude on an invoice |
| `/python-sdk/vlm-transcription` | `POST /api/extraction/describe` | Custom-prompt transcription via `Vision.describe()` (`level=standard\|detailed`) |
| `/python-sdk/table-extraction` | `POST /api/extraction/tables?provider=claude\|openai` | Structured table extraction — per-cell row/column/span/confidence |
| `/python-sdk/markdown-extraction` | `POST /api/extraction/markdown?provider=claude\|openai` | Document → clean Markdown for RAG/LLM ingestion (output sanitized with `rehype-sanitize` — see frontend PR #24) |
| `/python-sdk/field-extraction` | `POST /api/extraction/fields?provider=claude\|openai` | Key-value extraction: native `KEY_VALUE_REGION` regions + schema-driven JSON via `Vision.describe()` |
| `/python-sdk/alt-text` | `POST /api/extraction/describe?level=...` | Image alt-text generation (standard/detailed) |
| `/python-sdk/form-detection` | `POST /api/forms/detect` | Form-field detection on IRS F940 with a confidence slider |
| `/python-sdk/form-fill` | `POST /api/forms/list-fields` + `POST /api/forms/fill-fields` | (existed before these sessions) |
| `/python-sdk/digital-signature` | `POST /api/signing/sign-demo` | (existed before these sessions) |
| `/python-sdk/redaction`, `word-template`, `office-to-pdf`, `md-to-pdf`, `pdf-to-html`, `pdf-to-office` | various | (existed before these sessions; redaction backend was broken until PR #17) |

---

## Major work that landed (chronological)

### 2026-05-28 → 06-01 session (PRs #1–#11; frontend #13–#22)

1. **SDK 1.0.6 migration.** Broke a stack of APIs (`VisionEngine.OCR` → `ADAPTIVE_OCR`, `FORM` license bit, VLM endpoint, `PdfSigner` removal). All caught and fixed; `tests/` covers the regressions.
2. **Form-field detection feature.** `POST /api/forms/detect` with `?confidence=` query param, plus a frontend demo page (IRS F940 with a slider).
3. **ICR engine quality investigation.** 18 real-world handwriting samples. Headline: ICR is unusable on cursive but works on clean print in forms. Claude transcribes the same cursive samples cleanly. Full writeup at `docs/sdk-feedback/2026-05-28-icr-engine-quality.md`.
4. **Claude-vs-ICR comparison artifacts.** Markdown + standalone HTML at `docs/sdk-feedback/claude-vs-icr-comparison/`. The HTML (`index.html`) is the stakeholder-presentation version.
5. **ICR/OCR/VLM/Transcription demo pages.** Four new pages with consistent layout.
6. **Discovered `Vision.describe()` honors a custom `standard_prompt`.** The SDK already has a high-quality transcription path; it just isn't documented as one. Exposed via `POST /api/extraction/describe`.
7. **Discovered `VlmProvider.CUSTOM` is fully functional.** Eleven configurable knobs. Real differentiator.
8. **Discovered `VLM_ENHANCED_ICR` works with `VlmProvider.CLAUDE`.** No localhost:1234 LM Studio needed; pass `?provider=claude`.
9. **Removed the `_vision_keep_alive` workaround.** Stress-tested on 1.0.6 — no SIGSEGV.
10. **Filed two JIRA bug reports** (SDK-003, SDK-026) from `docs/sdk-feedback/bug-reports/`.

### 2026-06-01 → 06-02 session (PR #13; frontend #23, #24)

11. **Four extraction demos end to end.** Backend: `/tables`, `/markdown`, `/fields`, `describe?level=`. Frontend: Table Extraction, Document to Markdown, Field Extraction, Image Alt Text pages. Plus an XSS fix (#24): `rehype-sanitize` after `rehype-raw` — VLM output from uploaded docs is untrusted.
12. **SDK defect-hunting suite (PR #14).** See the dedicated section above.

### 2026-06-03 session (PRs #15–#18)

13. **Pre-render format fix (PR #15).** First live run of the OpenAI parity tests exposed that the "PNG pre-render" had been writing TIFF bytes all along (SDK-030: `export_as_image()` ignores the output extension). OpenAI rejects TIFF; a true-PNG re-encode then broke Claude (the SDK's internal upload re-encode pushed a 6.2 MB PNG past Anthropic's 10 MB cap). Fix: re-encode to JPEG q90 via Pillow — same pixel dimensions, ~1 MB. **Don't change the pre-render format without running both provider paths** (`pytest -k openai` + the Claude fields tests); on-disk size ≠ wire size.
14. **OpenAI provider parity verified.** Both parity tests (tables, fields) run live and pass. `make test` is fully green for the first time: 24 passed, 0 skipped.
15. **`.env.example` completed (PR #16).** Added the two LLM keys.
16. **Shipped-code bugs fixed (PR #17).** Redaction endpoint + FORM opt-out; see the suite section above.
17. **Fork-crash tests gated (PR #18).** No more macOS crash dialogs from `make test-sdk`; opt back in with `SDK_FORK_CRASH_TESTS=1`.
18. **`make install` fixed.** The gitignored local `recipes/` corpus broke setuptools flat-layout auto-discovery; `[tool.setuptools.packages.find] include = ["app*"]` declares the package explicitly.

---

## Key files for the next session

### Code

| File | Why it matters |
|---|---|
| `app/services/extraction.py` | All Vision API wrappers. `_prepared_input` holds the **PDF pre-render workaround** — renders page 1 to JPEG q90 via Pillow (see Known Bugs below for why JPEG specifically). |
| `app/services/forms.py` | Form list/fill/detect. `detect_fields()` accepts an optional `confidence_threshold`. |
| `app/services/redaction.py` | Fixed in PR #17: 0-based API page index → 1-based SDK `get_page()`. |
| `app/services/signing.py` | Uses the new `Signature` API (post-1.0.6 rename from `PdfSigner`). |
| `app/routers/extraction.py` | `/ocr`, `/icr`, `/vlm` (with `?provider=`), `/describe` (with `prompt`, `provider`, `level`), `/tables`, `/markdown`, `/fields`. |
| `tests/test_extraction.py` | All extraction paths incl. the JPEG pre-render regression test and the full-feature-set pin. |
| `tests/test_redaction.py` | First integration test for the redaction endpoint. |
| `tests/sdk/` | The defect-hunting suite (see dedicated section). |
| `Makefile` | `make test`, `make test-sdk`, `make dev`, `make install`. |
| `pyproject.toml` | SDK pins, Pillow dep, explicit package discovery, `addopts = "-p no:faulthandler"` (don't remove without re-validating; the SDK uses SIGSEGV internally). |

### Docs

| Folder | What's there |
|---|---|
| `docs/sdk-feedback/` | All SDK quality writeups. The big one is `2026-05-28-icr-engine-quality.md`. |
| `docs/sdk-feedback/DEFECTS.md` | The 35-defect registry, kept in lockstep with `tests/sdk/`. |
| `docs/sdk-feedback/bug-reports/` | JIRA-ready defect writeups (2 filed, 6 pending). |
| `docs/sdk-feedback/claude-vs-icr-comparison/` | The stakeholder presentation. `index.html` is the polished version. |
| `docs/superpowers/plans/` · `docs/superpowers/specs/` | Implementation plans and design docs (all executed). |

### External

- `recipes/` (gitignored; locally in working tree) — 18 handwriting samples from Reddit corpora used in the ICR investigation. Not redistributable. The ICR transcripts are at `recipes/icr-results/*.txt`. **Its presence is why package discovery is declared explicitly in pyproject.toml.**
- The companion repo (`nutrient-sdk-samples`) has its own `README.md` with setup instructions for both Python and .NET SDK demos.

---

## Known SDK issues — read before debugging

### Filed as bugs (in `docs/sdk-feedback/bug-reports/`)

1. **`Vision.set()` fails on image-only PDFs** (SDK-026). Scanned invoices throw `imageFilePath parameter is required`. Workaround: pre-render the PDF (already implemented in `_prepared_input`).
2. **Vision SDK has process-wide state corruption after any failed call** (SDK-003). Once one Vision call fails on a bad input, every subsequent Vision call in the same Python process fails with the same exception. This is why we always pre-render PDFs *before* the first Vision call.

### Not filed but worth knowing

3. **`export_as_image()` writes TIFF regardless of output extension** (SDK-030 — catalogued, not yet filed). This silently broke the OpenAI provider path until PR #15. The pre-render re-encodes to JPEG q90; OpenAI rejects TIFF and lossless PNG can exceed Anthropic's 10 MB request cap after the SDK's internal upload re-encode. **Now an interop bug, not a cosmetic one — strengthen the filing accordingly.**
4. **Documented confidence thresholds on ICR are no-ops.** Accept values, don't change output.
5. **`AiAugmenter.enable_*` flags are all no-ops on ICR.** All 5 toggles produce byte-identical output.
6. **ICR confidence scores are uncorrelated with output quality.** Don't build threshold-based auto-accept logic on them.
7. **The form-detection engine returns generic `PdfFormField` instances, not subtypes** (SDK-017).
8. **The PDF pre-render workaround only handles the first page** (`export_as_image()` writes one image). Multi-page scanned PDFs lose pages 2+. Acceptable for the current demo; a real fix needs page iteration.
9. **`VisionFeatures.KEY_VALUE_REGION` appears to be a no-op on tested documents.** Licensed (shows in the SDK banner) but `nativeRegions` comes back `[]` on `ocr-invoice.pdf`. This is why `/api/extraction/fields` pairs it with a schema-driven `describe()` prompt, which does return the requested fields cleanly. **Candidate for a separate SDK-feedback filing.**
10. **The SDK is not fork-safe on macOS** (SDK-034/035). `sign()` and `Vision.describe()` abort/crash in `fork()`ed children. Use spawned subprocesses.

---

## Pending external action

| Item | Status |
|---|---|
| **File the 6 JIRA bug-report stubs** | Ready at `docs/sdk-feedback/bug-reports/`: SDK-002, 007, 011, 017, 025, 029. (SDK-003, SDK-026 filed earlier.) |
| **File the `KEY_VALUE_REGION` no-op** as SDK feedback | Not yet written up as a stub; evidence is in the engine-quality doc + the `/fields` implementation notes. Consider also upgrading the SDK-030 (TIFF-only exporter) writeup with the OpenAI-interop angle from PR #15. |
| **Manager review of the comparison HTML** | `docs/sdk-feedback/claude-vs-icr-comparison/index.html` — outcome still unknown. |
| **(Maybe) refresh `tests/fixtures/`** with newer sample images | The Reddit-corpus images in `recipes/` are not committed (not redistributable). Re-fetch manually if rerunning the ICR investigation. |

Resolved since the last handoff: OpenAI key (valid locally + Railway, parity tests green), Anthropic-key rotation concern (user decided no rotation needed — sole possessor, local-only until the Railway add), both shipped-code bugs, macOS crash popups.

---

## Things explicitly out of scope / decided against

- **Multi-page PDF support in the pre-render workaround.** Single-page only for now; documented in the bug report.
- **`Vision.transcribe()` API as a separate ask.** Downgraded after discovering the custom-prompt path works — a documentation gap, not a missing feature.
- **Replacing ICR with VLM in the demo entirely.** The ICR Extraction page stays as a sibling to VLM Transcription — they tell different stories.
- **Rotating the exposed Anthropic key.** User decision 2026-06-03: sole possessor, key was local-only its entire life until the user added it to Railway themselves. Do not re-raise unless new exposure occurs.
- **Benchmarking against Google Document AI / AWS Textract / Azure Document Intelligence.** Recommended in the comparison doc's engineering-feedback section but not executed.

---

## How to resume quickly

If picking up cold:

1. `cd /Users/jonaddamsnutrient/SE/code/python-fast-api && make test` — confirm baseline (**24 passed, 0 skipped**, ~3 min; live VLM/Claude/OpenAI calls).
2. `make test-sdk` — **38 passed / 38 xfailed / 2 skipped**, ~35s. (The 2 skips are the gated fork-crash tests; `SDK_FORK_CRASH_TESTS=1` runs them but pops macOS crash dialogs by design.)
3. Read `docs/sdk-feedback/DEFECTS.md` — the defect registry is the most important context.
4. Skim `docs/sdk-feedback/2026-05-28-icr-engine-quality.md` to refresh on the ICR/VLM story.
5. `git log --oneline -20` — recent PR history is informative.
6. Check `.env` is intact (NUTRIENT_LICENSE_KEY with `vision_form` entitlement, ANTHROPIC_API_KEY, OPENAI_API_KEY — all valid as of 2026-06-03).

If there's a specific question about why some setting or workaround is there, search the engine-quality doc and DEFECTS.md first — most of the surprises are documented.
