# Form Field Detection — Design

**Date:** 2026-05-28
**Status:** Approved, awaiting implementation plan
**Repos touched:** `python-fast-api` (backend), `nutrient-sdk-samples` (frontend)

## Goal

Expose `nutrient-sdk` 1.0.6's new `PdfEditor.detect_and_add_form_fields()` API as a demo: a customer uploads (or loads a sample) PDF that has no form fields, the backend runs ML-based detection, and the frontend shows a stats summary plus the modified PDF rendered in the Nutrient viewer.

## Verified background

A throwaway spike on 2026-05-28 confirmed:

- The API is wired in 1.0.6: `from nutrient_sdk import PdfEditor` → `editor = PdfEditor.edit(document)` → `editor.detect_and_add_form_fields()` → `editor.save_as("output.pdf")`.
- Running against the official sample (`input_forms_detection.pdf`, 43,513 bytes) added **13 form fields** to a PDF that had **0** before.
- The feature requires the `vision_form` license entitlement. The demo key used during the SDK 1.0.6 migration did NOT have it; a refreshed key from 2026-05-28 does. The same entitlement gates `VisionFeatures.FORM` in the Vision pipeline.
- Form-field enumeration after detection uses `editor.get_form_field_collection()` (returns `PdfFormFieldCollection` with `.get_count()`, `.get_enumerator()`).

## Architecture

```
nutrient-sdk-samples (Next.js)              python-fast-api (FastAPI)
┌──────────────────────────────┐            ┌──────────────────────────────┐
│ app/python-sdk/              │            │ app/routers/forms.py         │
│   form-detection/page.tsx    │── POST ──▶ │   @router.post("/detect")    │
│                              │  multipart │                              │
│   ┌─ Stats card ─┐           │            │ app/services/forms.py        │
│   │ count, types │           │            │   detect_fields(pdf_bytes)   │
│   │ Detect btn   │           │            │      └─▶ PdfEditor + SDK     │
│   └──────────────┘           │            │                              │
│   ┌─ PdfViewer ──┐           │ ◀── JSON ──│ Response:                    │
│   │ /documents/  │           │            │   { counts, fields[], b64 }  │
│   │ input...pdf  │           │            │                              │
│   └──────────────┘           │            │ tests/test_forms_detect.py   │
│                              │            │   fixture: input_forms…pdf   │
│ public/documents/            │            │ tests/fixtures/              │
│   input_forms_detection.pdf  │            │   input_forms_detection.pdf  │
└──────────────────────────────┘            └──────────────────────────────┘
```

## Backend

### Files

- **Modify** `app/services/forms.py` — add `detect_fields(pdf_bytes: bytes) -> dict`.
- **Modify** `app/routers/forms.py` — add `@router.post("/detect")` and route the license-gate error to HTTP 403.
- **Create** `tests/test_forms_detect.py` — integration test.
- **Create** `tests/fixtures/input_forms_detection.pdf` — checked-in copy of Nutrient's official sample (43,513 bytes, from `https://www.nutrient.io/downloads/samples/python/detect-and-add-form-fields.zip`).

### Service function

```python
def detect_fields(pdf_bytes: bytes) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out:
        inp.write(pdf_bytes); inp_path, out_path = inp.name, out.name
    try:
        with Document.open(inp_path) as doc:
            editor = PdfEditor.edit(doc)
            try:
                input_count = editor.get_form_field_collection().get_count()
                editor.detect_and_add_form_fields()
                collection = editor.get_form_field_collection()
                detected_count = collection.get_count()
                fields = _enumerate_fields(collection)
                editor.save_as(out_path)
            finally:
                editor.close()
        with open(out_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("ascii")
        return {
            "inputFieldCount": input_count,
            "detectedFieldCount": detected_count,
            "addedFields": fields,
            "pdfBase64": pdf_b64,
        }
    finally:
        os.unlink(inp_path); os.unlink(out_path)
```

`_enumerate_fields` returns `[{"name": <full_name>, "type": <class-name-without-Pdf-prefix>}, ...]`. The exact `PdfFormFieldCollection` iteration API will be confirmed during implementation — `get_enumerator()` returns an iterator-style object; if it follows the standard .NET-like protocol (`move_next()` / `current`), use that; otherwise iterate via index if `find_by_full_name` plus a known names list is the only path. **Plan task should test the enumeration API once before committing to a shape.**

### Router

```python
class LicenseFeatureMissing(RuntimeError): ...

@router.post("/detect")
async def detect(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return detect_fields(data)
    except Exception as e:
        msg = str(e)
        if "vision_form" in msg or "(Error Code: 3017)" in msg:
            raise HTTPException(
                status_code=403,
                detail="Form field detection requires the 'vision_form' license entitlement. Your license does not include it.",
            )
        raise HTTPException(status_code=500, detail=msg)
```

(Same translate-string-match-to-typed-response pattern used for `LocalVlmUnavailable` in extraction.)

### Test

`tests/test_forms_detect.py` uses the conftest `client` fixture. Reads `tests/fixtures/input_forms_detection.pdf`, POSTs to `/api/forms/detect`, asserts:

1. HTTP 200.
2. `inputFieldCount == 0`.
3. `detectedFieldCount > 0` (precise value not asserted — model output may shift across SDK builds).
4. `len(addedFields) == detectedFieldCount`.
5. `base64.b64decode(body["pdfBase64"])[:5] == b"%PDF-"`.
6. The decoded PDF is strictly larger than the input.

## Frontend

### Files

- **Create** `app/python-sdk/form-detection/page.tsx`.
- **Create** `public/documents/input_forms_detection.pdf` — same fixture as the backend, ~43 KB.

### Page shape

State:
```ts
type AddedField = { name: string; type: string };
type DetectResult = {
  inputFieldCount: number;
  detectedFieldCount: number;
  addedFields: AddedField[];
  pdfBase64: string;
};

const [result, setResult] = useState<DetectResult | null>(null);
const [pdfUrl, setPdfUrl] = useState<string>("/documents/input_forms_detection.pdf");
const [processing, setProcessing] = useState(false);
const [error, setError] = useState<string | null>(null);
```

Layout (mirrors `form-fill/page.tsx`):
- `<PythonSampleHeader …>` at top with title, doc-guide link.
- Two-column grid below:
  - Left: stats card.
    - Pre-detection (`result === null`): "0 fields detected · click below to scan with ML" + `[Detect form fields]` button.
    - Post-detection: detected count headline + a type-breakdown list (e.g. "10 text, 2 checkbox, 1 signature") computed from `result.addedFields`. Plus a `[Reset]` button that re-loads the original PDF and clears `result`.
    - Error state: red banner with `error` text.
  - Right: `<PdfViewer documentUrl={pdfUrl} toolbarItems={TOOLBAR_ITEMS} />`.

Detect flow:
1. Fetch the sample PDF from `/documents/input_forms_detection.pdf` as a blob.
2. POST as multipart `file` to `${API_BASE}/api/forms/detect`.
3. On `!res.ok`: parse `res.json()`, surface `detail` (same code shape pushed for VLM).
4. On success: `setResult(data)`; decode `data.pdfBase64` to a `Blob` (`application/pdf`) and replace `pdfUrl` with `URL.createObjectURL(blob)`. Revoke the previous object URL.

Reset flow: revoke the current object URL, set `pdfUrl` back to `/documents/input_forms_detection.pdf`, `setResult(null)`.

### Type breakdown helper

```ts
function summarizeFieldTypes(fields: AddedField[]): string {
  const counts = new Map<string, number>();
  for (const f of fields) counts.set(f.type, (counts.get(f.type) ?? 0) + 1);
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([t, n]) => `${n} ${t.toLowerCase().replace(/^pdf|field$/g, "")}`)
    .join(", ");
}
```

(Converts `"PdfTextField"` → `"text"`, etc. Exact regex confirmed in implementation.)

## Error handling

| Condition | Backend | Frontend |
|---|---|---|
| Missing `vision_form` license | 403 with `detail` text | Surfaces `detail` verbatim |
| Unexpected SDK error | 500 with `detail` (raw `str(e)`) | Surfaces `detail` |
| Network failure | n/a | Falls back to "Detection failed" |

The license-gate error currently surfaces in the SDK as `InvalidLicenseException` with substring `feature 'vision_form'` and `Error Code: 3017`. The router's string match uses both `"vision_form"` and `"(Error Code: 3017)"` as a belt-and-suspenders check.

## Testing

- **Backend** — one pytest integration test (`test_forms_detect.py`) hits the real SDK via the test client. Total suite after this change: 5 tests.
- **Frontend** — manual smoke against a running backend. No test framework added.
- **Smoke checklist after wiring** (added to the implementation plan):
  - `curl -F "file=@tests/fixtures/input_forms_detection.pdf" http://localhost:8080/api/forms/detect | jq '.detectedFieldCount, (.pdfBase64 | length)'` returns a non-zero count and a large base64 string.
  - Frontend page renders the input PDF, button triggers detection, stats update, viewer swaps to the output PDF, reset restores the input.

## Out of scope (do NOT pick up in the implementation plan)

- **Field editing UX** — the Nutrient viewer already supports edit-mode natively; no in-page editor.
- **Customizing `FormRecognitionSettings`** (confidence threshold, model_path, etc.) — SDK defaults are used. If the demo ever needs tuning, add it then.
- **Download-the-PDF button** — the user explicitly chose the no-download variant for this iteration. Easy to add later.
- **User-uploaded PDFs** — only the shipped sample is supported on the frontend. The backend endpoint will accept any PDF, but the frontend page does not expose a file picker.
- **OCR/text-only PDFs** — detector quality on scanned documents is undefined and not part of this demo.
- **Caching** — every click re-runs detection. Acceptable for a demo.

## Open questions to resolve during planning

- Exact iteration API for `PdfFormFieldCollection` (verified in spike that `get_enumerator()` exists; the protocol — `move_next()`/`current` vs. Pythonic — wasn't fully validated). The plan must include a one-line investigation task before writing the service code, OR fall back to `find_by_full_name` with names from a known list, OR iterate via `range(get_count())` if positional accessors exist.
