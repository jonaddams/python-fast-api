# Design — Extraction demo expansion

Date: 2026-06-01
Status: Approved (pending user review of this spec)
Scope: Backend (`python-fast-api`). Frontend pages are a paired follow-up in `nutrient-sdk-samples`.

## Goal

Extraction is the most powerful feature of the Nutrient Python SDK, but the current
demos only exercise a fraction of it (raw OCR, ICR, VLM-ICR, `describe()` with a
custom prompt, form-field detection). This project adds four customer-facing demos
that showcase the untapped, high-value extraction capabilities:

1. **Table extraction** — structured rows/columns out of an invoice.
2. **Key-value / field extraction** — pull labeled fields into clean JSON.
3. **Document → Markdown** — convert a complex document to clean Markdown for RAG/LLM ingestion.
4. **Accessibility alt-text** — generate WCAG-style image descriptions.

Audience is **tiered**: a polished outcome on top (rendered table, rendered Markdown,
field cards, alt-text) with the raw request/response and a code snippet underneath for
the technical evaluator.

## Key finding that shapes the design

A live spike on 2026-06-01 against `tests/fixtures/ocr-invoice.pdf` established that
structured extraction (tables, document roles, clean Markdown) **only works through the
`VLM_ENHANCED_ICR` engine with `provider=claude`**. On the local `ADAPTIVE_OCR`/`ICR`
engines the `TABLE`/`KEY_VALUE_REGION` feature flags are no-ops (output was 49 plain
`paragraph` elements) and Markdown output is jumbled.

| Capability | Local OCR/ICR | VLM + Claude |
|---|---|---|
| Table structure | no-op (flat paragraphs) | `table` elements w/ `rowCount`, `columnCount`, `cells[]` (row/col/span/text/bounds/confidence) |
| Document structure | flat text | roles: `Header`, `Footer`, `SectionHeader`, `Text`; types `paragraph`/`table`/`picture` |
| Markdown output | jumbled, unusable | clean Markdown w/ headings + embedded HTML tables |

This is a coherent story for the demos: **one API — compose `VisionFeatures`, pick a
`VisionOutputFormat`, get exactly the shape you need.** Three of the four demos build on
the existing `?provider=claude` VLM plumbing; the fourth reuses the existing `describe()`
path.

## Backend architecture

Extend `app/services/extraction.py` and `app/routers/extraction.py` following the
existing thin-wrapper pattern. Generalize the current `_run_vision` core to accept
`features`, `output_format`, and an optional `system_prompt`, then add named presets on
top — mirroring how `extract_text_ocr/icr/vlm` already wrap `_extract_with_engine`.

| Endpoint | Engine | Feature(s) / format | Returns |
|---|---|---|---|
| `POST /api/extraction/tables` | `VLM_ENHANCED_ICR` + claude | `TABLE`, JSON | `tables[]` of `{rowCount, columnCount, cells[]}` |
| `POST /api/extraction/markdown` | `VLM_ENHANCED_ICR` + claude | `MARKDOWN` output format | `{markdown}` |
| `POST /api/extraction/fields` | `VLM_ENHANCED_ICR` + claude | **both**: native `KEY_VALUE_REGION` **and** custom-prompt schema | `{schemaFields, nativeRegions[]}` |
| `POST /api/extraction/describe` *(reuse existing)* | `describe()` | `level=DETAILED` | `{text}` — surface the existing `level` knob |

All endpoints inherit the existing safeguards:
- PDF → PNG pre-render before the first Vision call (works around the image-only-PDF
  failure and the resulting process-wide state corruption — see
  `docs/sdk-feedback/bug-reports/`).
- `LocalVlmUnavailable` → HTTP 503; generic exceptions → HTTP 500.

### Shared core

```
_run_vision(path, engine, *, features, output_format, provider, system_prompt=None) -> str
```

Each endpoint is a thin preset that calls this core with fixed arguments. This keeps
each handler readable as a single purpose while avoiding duplication of the
engine/feature/provider wiring.

## The four demos

Each is a sibling page under `/python-sdk` in the companion repo, matching the existing
OCR/ICR/VLM/form layout convention. Each page is tiered (polished result on top, raw
payload + code snippet below).

### 1. Table extraction
- **Sample:** a clean born-digital invoice from `nutrient-sdk-samples/public/invoices/`
  (e.g. `Invoice GL-2025-0088.pdf`). Born-digital gives the cleanest table output;
  the scanned `ocr-invoice.pdf` is an alternate that also shows OCR + structure.
- **Top tier:** rendered HTML table(s), with optional bounding-box overlay on the source.
- **Bottom tier:** raw `cells[]` JSON + a code snippet showing the `TABLE` feature + JSON
  output-format setup.

### 2. Key-value / field extraction
- **Samples:** the invoice (for schema fields: invoice #, total, due date) plus a
  form-like doc (`patient-intake-form.pdf`) for the native-region path.
- **Top tier:** clean field cards produced by schema-driven extraction; a side panel
  showing the native `KEY_VALUE_REGION` output.
- **Bottom tier:** both raw payloads.
- **Mechanism (both, side by side):**
  - *Schema-driven:* the user supplies the field names they want; a custom prompt
    instructs the VLM to return those fields as a JSON object. This is the compelling
    "data-entry automation" story. Framed honestly as prompt-driven structured output,
    not a native field API.
  - *Native:* the SDK's `KEY_VALUE_REGION` layout feature, rendering whatever
    region-tagged elements it returns.

### 3. Document → Markdown
- **Sample:** `usenix-example-paper.pdf` (multi-section, tables, headings — strong RAG
  ingestion story).
- **Top tier:** source PDF on the left, rendered Markdown on the right.
- **Bottom tier:** raw Markdown + a short "why this matters for RAG/LLM ingestion" note.

### 4. Accessibility alt-text
- **Sample:** a figure/chart image. Preferred: dogfood HTML → PDF → PNG via the Nutrient
  SDK to create a clean chart. Fallback: an existing figure image (e.g. `macaques.pdf`
  rasterized).
- **Top tier:** the image + the generated `DETAILED` description, framed as WCAG/ADA alt-text.
- **Bottom tier:** `STANDARD` vs `DETAILED` comparison + the prompt used.
- Reuses the existing `/api/extraction/describe` endpoint; only the `level` knob is newly surfaced.

## Output shapes & data flow

Response envelopes stay consistent with the existing extraction format (`engine`,
`filename`, plus capability-specific payload):

- **tables**: `{engine, filename, tableCount, tables: [{rowCount, columnCount, cells: [{row, column, rowSpan, colSpan, text, confidence, bounds}]}], rawElements}`
- **markdown**: `{engine, filename, markdown, charCount}` — Markdown verbatim from the SDK.
- **fields**: `{engine, filename, schemaFields: {<requested field>: value}, nativeRegions: [{key, value, confidence, bounds}], rawElements}`. The `fields` form param accepts a comma-separated list or JSON array of field names to drive the schema prompt.
- **describe (alt-text)**: existing shape, with `level` echoed back.

## Error handling

Reuse existing patterns: pre-render before the first Vision call; `LocalVlmUnavailable`
→ 503; generic exceptions → 500. The schema-driven `fields` path parses the model's JSON
response **defensively** — if the VLM returns non-JSON or partial JSON, the endpoint
returns the raw text under a `parseError` key rather than raising 500, so the demo
degrades visibly instead of failing silently. No silent fallbacks.

## Testing

Integration tests in `tests/` against the real SDK (no mocks), matching the existing
convention. Because three of four demos make **live Claude calls**, gate those behind
`ANTHROPIC_API_KEY` presence with `pytest.mark.skipif` so the suite stays green in
keyless CI.

- `test_extraction_tables.py` — assert ≥1 table with `cells[]` and consistent
  `rowCount`/`columnCount`.
- `test_extraction_markdown.py` — assert non-empty Markdown containing a heading and a
  table marker.
- `test_extraction_fields.py` — assert requested schema fields are present; assert the
  native-region path returns without error (lenient, since it may be weak).
- Alt-text: extend the existing `describe` test to cover `level=DETAILED`.

Fixtures: copy the chosen invoice, the usenix paper, and the chart image into
`tests/fixtures/` (committed — they already ship in the public Next app, so they are
redistributable).

## Risks / things to verify during implementation

1. **Native `KEY_VALUE_REGION` may be a no-op** on form docs (like other documented SDK
   features). Verify early in the Fields slice; if weak, demo schema-only and file an
   SDK-feedback note under `docs/sdk-feedback/`.
2. **Markdown table format**: the SDK emits HTML `<table>` inside Markdown (observed in
   the spike), not GFM pipe tables. The frontend renderer must handle embedded HTML —
   note for the companion repo.
3. **Live-call cost/latency**: each demo run hits Claude. Acceptable (matches the
   existing VLM demo), but pages should show a loading state.
4. **Synthetic chart for alt-text**: if HTML → PDF → PNG dogfooding is fiddly, fall back
   to an existing figure image.
5. **Frontend boundary**: this spec covers the backend (`python-fast-api`). Frontend
   pages are a paired follow-up in `nutrient-sdk-samples`.

## Build sequence

Four vertical backend slices, each = service preset + router endpoint + test + fixture,
landed independently:

1. **Tables** (highest wow, proven plumbing)
2. **Markdown**
3. **Fields** (both mechanisms; carries the `KEY_VALUE_REGION` verification risk)
4. **Alt-text** (smallest — reuses `describe()`)

Frontend pages follow per-slice in the companion repo.

## Out of scope

- Frontend implementation (companion repo, paired follow-up).
- `EQUATION` and `IMAGE_CLASSIFICATION` features (deferred; not in the chosen four).
- A unified "extraction studio" UI (rejected in favor of four sibling pages).
- Non-Claude VLM providers for the new demos (OpenAI path remains blocked on a valid key).
