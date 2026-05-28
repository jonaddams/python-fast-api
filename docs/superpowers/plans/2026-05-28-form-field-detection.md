# Form Field Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `POST /api/forms/detect` endpoint to `python-fast-api` that runs `PdfEditor.detect_and_add_form_fields()` and returns metadata + the fielded PDF as base64. Wire a new `/python-sdk/form-detection` page in `nutrient-sdk-samples` that loads a sample PDF, lets the user trigger detection, and shows a stats card alongside the result PDF in the Nutrient viewer.

**Architecture:** Backend service `detect_fields(pdf_bytes)` in `app/services/forms.py` returns `{inputFieldCount, detectedFieldCount, addedFields[], pdfBase64}`. Router endpoint in `app/routers/forms.py` maps the `vision_form` license-gate exception to HTTP 403. Frontend page mirrors the existing `app/python-sdk/form-fill/page.tsx` structure: stats card on the left, Nutrient `PdfViewer` on the right, one Detect button. The same Nutrient official sample PDF (`input_forms_detection.pdf`) is checked into both repos.

**Tech Stack:** Python 3.12, FastAPI, `nutrient-sdk==1.0.6`, pytest, Next.js (React 18), Nutrient Web SDK viewer via the existing `PdfViewer` wrapper.

**Spec:** [`docs/superpowers/specs/2026-05-28-form-field-detection-design.md`](../specs/2026-05-28-form-field-detection-design.md)

---

## Resolved during planning (no investigation task needed)

The spec flagged the `PdfFormFieldCollection` enumeration API as an open question. Reading `app/services/forms.py:22-30` shows the existing `list_form_fields` function already uses positional access:

```python
for i in range(fields.get_count()):
    field = fields.get_item(i)
```

Use the same pattern. No spike required.

---

## File Map

| Repo | File | Action | Responsibility |
|---|---|---|---|
| `python-fast-api` | `tests/fixtures/input_forms_detection.pdf` | Create | Test fixture — Nutrient official sample, 43,513 bytes |
| `python-fast-api` | `tests/test_forms_detect.py` | Create | Integration test for `/api/forms/detect` |
| `python-fast-api` | `app/services/forms.py` | Modify | Add `detect_fields()` plus `LicenseFeatureMissing` exception |
| `python-fast-api` | `app/routers/forms.py` | Modify | Add `@router.post("/detect")` + license-gate mapping |
| `nutrient-sdk-samples` | `public/documents/input_forms_detection.pdf` | Create | Same PDF as backend fixture, served to the frontend |
| `nutrient-sdk-samples` | `app/python-sdk/form-detection/page.tsx` | Create | New demo page |

---

## Background for the implementing engineer

This is a feature-add that spans two repos. Backend work happens in `/Users/jonaddamsnutrient/SE/code/python-fast-api` (current branch will be a new feature branch off `main`). Frontend work happens in `/Users/jonaddamsnutrient/SE/code/nutrient-sdk-samples` (also a new feature branch off `main`).

The `vision_form` license entitlement is required. The developer's `.env` was refreshed on 2026-05-28 with a key that includes it. If the test fails with `InvalidLicenseException` and `feature 'vision_form'`, the license is wrong — not the code.

The official sample PDF is hosted by Nutrient at `https://www.nutrient.io/downloads/samples/python/detect-and-add-form-fields.zip`. The ZIP contains `input_forms_detection.pdf` (43,513 bytes) which the spike verified produces 13 detected fields.

`PdfFormFieldCollection` enumeration uses `get_count()` + `get_item(i)` (positional), as already established in `app/services/forms.py:22-30`.

---

## Task 1: Add backend fixture + failing integration test

**Repo:** `python-fast-api`

**Files:**
- Create: `tests/fixtures/input_forms_detection.pdf`
- Create: `tests/test_forms_detect.py`

- [ ] **Step 1: Create a feature branch**

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
git checkout main && git pull
git checkout -b form-field-detection
```

- [ ] **Step 2: Download and check in the sample PDF**

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
TMPDIR=$(mktemp -d)
curl -sLo "$TMPDIR/sample.zip" "https://www.nutrient.io/downloads/samples/python/detect-and-add-form-fields.zip"
unzip -p "$TMPDIR/sample.zip" input_forms_detection.pdf > tests/fixtures/input_forms_detection.pdf
rm -rf "$TMPDIR"
ls -la tests/fixtures/input_forms_detection.pdf
```

Expected: file exists, ~43,513 bytes. (Slight size variance OK if Nutrient updates the sample.)

- [ ] **Step 3: Write the failing test**

Create `tests/test_forms_detect.py`:

```python
import base64
from pathlib import Path

from fastapi.testclient import TestClient

SAMPLE_PDF = Path(__file__).resolve().parent / "fixtures" / "input_forms_detection.pdf"


def test_detect_endpoint_adds_form_fields(client: TestClient):
    pdf_bytes = SAMPLE_PDF.read_bytes()
    response = client.post(
        "/api/forms/detect",
        files={"file": (SAMPLE_PDF.name, pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["inputFieldCount"] == 0
    assert body["detectedFieldCount"] > 0
    assert len(body["addedFields"]) == body["detectedFieldCount"]

    for field in body["addedFields"]:
        assert isinstance(field["name"], str) and field["name"]
        assert isinstance(field["type"], str) and field["type"].startswith("Pdf")

    decoded = base64.b64decode(body["pdfBase64"])
    assert decoded[:5] == b"%PDF-"
    assert len(decoded) > len(pdf_bytes)
```

- [ ] **Step 4: Run the test to verify it fails**

```bash
.venv/bin/pytest tests/test_forms_detect.py -v
```

Expected: FAIL with `assert 404 == 200` (route doesn't exist yet). `response.text` will contain `{"detail":"Not Found"}`.

- [ ] **Step 5: Commit fixture + failing test**

```bash
git add tests/fixtures/input_forms_detection.pdf tests/test_forms_detect.py
git commit -m "test(forms): add failing /api/forms/detect integration test and sample PDF fixture"
```

---

## Task 2: Implement `detect_fields` service + router endpoint

**Repo:** `python-fast-api`

**Files:**
- Modify: `app/services/forms.py` (add to existing file, do not touch `list_form_fields` or `fill_form_fields`)
- Modify: `app/routers/forms.py` (add new route + import)

- [ ] **Step 1: Add imports + exception + service function in `app/services/forms.py`**

Append to `app/services/forms.py` (at the end of the file, after `fill_form_fields`):

```python
import base64


class LicenseFeatureMissing(RuntimeError):
    """Raised when the SDK rejects a call for a missing license feature."""


def detect_fields(pdf_bytes: bytes) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out:
        inp.write(pdf_bytes)
        inp_path, out_path = inp.name, out.name

    try:
        try:
            with Document.open(inp_path) as doc:
                editor = PdfEditor.edit(doc)
                try:
                    input_count = editor.get_form_field_collection().get_count()
                    editor.detect_and_add_form_fields()

                    fields = editor.get_form_field_collection()
                    detected_count = fields.get_count()
                    added = []
                    for i in range(detected_count):
                        f = fields.get_item(i)
                        added.append({
                            "name": f.get_full_name(),
                            "type": type(f).__name__,
                        })

                    editor.save_as(out_path)
                finally:
                    editor.close()
        except Exception as ex:
            msg = str(ex)
            if "vision_form" in msg or "Error Code: 3017" in msg:
                raise LicenseFeatureMissing(
                    "Form field detection requires the 'vision_form' license "
                    "entitlement. Your license does not include it."
                ) from ex
            raise

        with open(out_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("ascii")

        return {
            "inputFieldCount": input_count,
            "detectedFieldCount": detected_count,
            "addedFields": added,
            "pdfBase64": pdf_b64,
        }
    finally:
        for p in (inp_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass
```

The `import base64` at the top of the appended block is a duplicate-safe addition. If the engineer prefers to consolidate imports, move it to the top of the file with the other imports — both are acceptable; the function body must not change.

- [ ] **Step 2: Wire the route in `app/routers/forms.py`**

Replace the import line (currently line 4):

```python
from app.services.forms import list_form_fields, fill_form_fields
```

with:

```python
from app.services.forms import (
    list_form_fields,
    fill_form_fields,
    detect_fields,
    LicenseFeatureMissing,
)
```

Append at the end of `app/routers/forms.py` (after the `fill_fields` handler):

```python
@router.post("/detect")
async def detect(file: UploadFile = File(...)):
    try:
        data = await file.read()
        return detect_fields(data)
    except LicenseFeatureMissing as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 3: Run the failing test from Task 1**

```bash
.venv/bin/pytest tests/test_forms_detect.py -v
```

Expected: PASS. Detection takes ~2-3 seconds (ML model loads on first run; subsequent calls in the same process are faster).

- [ ] **Step 4: Run the full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: 5 passed (the existing 4 + the new one).

- [ ] **Step 5: Commit**

```bash
git add app/services/forms.py app/routers/forms.py
git commit -m "feat(forms): add /api/forms/detect endpoint using PdfEditor.detect_and_add_form_fields"
```

- [ ] **Step 6: Quick curl smoke**

Start the server in one terminal:

```bash
.venv/bin/uvicorn app.main:app --port 8080
```

In another terminal:

```bash
curl -s -X POST -F "file=@tests/fixtures/input_forms_detection.pdf" \
  http://localhost:8080/api/forms/detect \
  | python -c "import sys,json; d=json.load(sys.stdin); print('input:', d['inputFieldCount'], 'detected:', d['detectedFieldCount'], 'pdfBase64 len:', len(d['pdfBase64']))"
```

Expected: `input: 0 detected: 13 pdfBase64 len: <large number>` (the count may vary by SDK build; non-zero is what matters). Stop the server.

- [ ] **Step 7: Push the backend branch and open a PR**

```bash
git push -u origin form-field-detection
gh pr create --title "Add form-field detection endpoint" --body "$(cat <<'EOF'
## Summary
- Exposes nutrient-sdk 1.0.6's `PdfEditor.detect_and_add_form_fields()` as `POST /api/forms/detect`.
- Returns JSON with input/detected counts, the detected fields, and the resulting PDF as base64.
- Maps the `vision_form` license-feature error to HTTP 403 with an explanatory detail (same pattern as the VLM 503).

## Test plan
- [x] `pytest tests/` — 5 passed (1 new)
- [x] Manual curl returns 13 detected fields against the Nutrient sample PDF

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

If the engineer would rather wait to push until the frontend is also done, they can skip Step 7 — but the PRs are independent, so pushing here is fine. Note the URL the PR command prints.

---

## Task 3: Add frontend fixture + page scaffolding

**Repo:** `nutrient-sdk-samples`

**Files:**
- Create: `public/documents/input_forms_detection.pdf`
- Create: `app/python-sdk/form-detection/page.tsx`

- [ ] **Step 1: Create a feature branch**

```bash
cd /Users/jonaddamsnutrient/SE/code/nutrient-sdk-samples
git checkout main && git pull
git checkout -b form-field-detection
```

- [ ] **Step 2: Copy the fixture from the backend repo**

```bash
cp /Users/jonaddamsnutrient/SE/code/python-fast-api/tests/fixtures/input_forms_detection.pdf \
   public/documents/input_forms_detection.pdf
ls -la public/documents/input_forms_detection.pdf
```

Expected: ~43,513 bytes.

- [ ] **Step 3: Create the page**

Create `app/python-sdk/form-detection/page.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { PdfViewer } from "../../java-sdk/_components/PdfViewer";
import { PythonSampleHeader } from "../_components/PythonSampleHeader";

const API_BASE =
  process.env.NEXT_PUBLIC_PYTHON_SDK_API_URL || "http://localhost:8080";

const SAMPLE_PDF = {
  label: "Form Detection Sample",
  path: "/documents/input_forms_detection.pdf",
  filename: "input_forms_detection.pdf",
};

const TOOLBAR_ITEMS = [
  { type: "zoom-out" },
  { type: "zoom-in" },
  { type: "zoom-mode" },
];

interface AddedField {
  name: string;
  type: string;
}

interface DetectResult {
  inputFieldCount: number;
  detectedFieldCount: number;
  addedFields: AddedField[];
  pdfBase64: string;
}

function prettyFieldType(typeName: string): string {
  return typeName.replace(/^Pdf/, "").replace(/Field$/, "").toLowerCase();
}

function summarizeFieldTypes(fields: AddedField[]): { type: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const f of fields) {
    const key = prettyFieldType(f.type);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([type, count]) => ({ type, count }));
}

function base64ToBlob(base64: string, mime: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

export default function FormDetectionPage() {
  const [result, setResult] = useState<DetectResult | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string>(SAMPLE_PDF.path);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Revoke object URL on unmount or when it changes
  useEffect(() => {
    return () => {
      if (pdfUrl.startsWith("blob:")) URL.revokeObjectURL(pdfUrl);
    };
  }, [pdfUrl]);

  const handleDetect = async () => {
    setProcessing(true);
    setError(null);
    try {
      const sampleRes = await fetch(SAMPLE_PDF.path);
      const sampleBlob = await sampleRes.blob();
      const file = new File([sampleBlob], SAMPLE_PDF.filename, {
        type: "application/pdf",
      });

      const formData = new FormData();
      formData.append("file", file);

      const apiRes = await fetch(`${API_BASE}/api/forms/detect`, {
        method: "POST",
        body: formData,
      });

      if (!apiRes.ok) {
        const detail = await apiRes
          .json()
          .then((b) => (typeof b?.detail === "string" ? b.detail : null))
          .catch(() => null);
        throw new Error(detail ?? `API returned ${apiRes.status}`);
      }

      const data: DetectResult = await apiRes.json();
      const blob = base64ToBlob(data.pdfBase64, "application/pdf");
      const newUrl = URL.createObjectURL(blob);

      if (pdfUrl.startsWith("blob:")) URL.revokeObjectURL(pdfUrl);
      setPdfUrl(newUrl);
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Form detection failed");
    } finally {
      setProcessing(false);
    }
  };

  const handleReset = useCallback(() => {
    if (pdfUrl.startsWith("blob:")) URL.revokeObjectURL(pdfUrl);
    setPdfUrl(SAMPLE_PDF.path);
    setResult(null);
    setError(null);
  }, [pdfUrl]);

  const breakdown = result ? summarizeFieldTypes(result.addedFields) : [];

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <PythonSampleHeader
        title="PDF Form Field Detection"
        description="Detect form fields in an unfielded PDF using the Nutrient Python SDK's machine-learning detector."
      />

      <main className="max-w-7xl mx-auto px-6 pt-6 pb-8">
        <div className="bg-[var(--bg-elev)] rounded-xl shadow-lg border border-[var(--line)] overflow-hidden h-[calc(100vh-12rem)]">
          <div className="flex h-full">
            {/* Left Panel — Stats / actions */}
            <div className="w-96 border-r border-[var(--line)] bg-[var(--bg-elev)] flex flex-col flex-shrink-0">
              <div className="p-4 border-b border-[var(--line)]">
                <h3 className="text-sm font-semibold text-[var(--ink-2)]">
                  Detection Results
                </h3>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {!result && !error && (
                  <p className="text-sm text-[var(--ink-3)]">
                    The sample PDF has <strong>0</strong> form fields. Click
                    “Detect form fields” to run ML detection on the document.
                  </p>
                )}

                {error && (
                  <div className="rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 p-3 text-sm text-red-700 dark:text-red-300">
                    {error}
                  </div>
                )}

                {result && (
                  <div className="space-y-3">
                    <div>
                      <p className="text-xs uppercase tracking-wide text-[var(--ink-3)]">
                        Fields detected
                      </p>
                      <p className="text-3xl font-semibold text-[var(--ink-1)]">
                        {result.detectedFieldCount}
                      </p>
                      <p className="text-xs text-[var(--ink-3)]">
                        from {result.inputFieldCount} in the source PDF
                      </p>
                    </div>

                    <div>
                      <p className="text-xs uppercase tracking-wide text-[var(--ink-3)] mb-1">
                        Breakdown
                      </p>
                      <ul className="text-sm text-[var(--ink-2)] space-y-1">
                        {breakdown.map((b) => (
                          <li key={b.type} className="flex justify-between">
                            <span>{b.type}</span>
                            <span className="font-medium">{b.count}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}
              </div>

              <div className="p-4 border-t border-[var(--line)] space-y-2">
                <button
                  type="button"
                  onClick={handleDetect}
                  disabled={processing || result !== null}
                  className="w-full px-3 py-2 rounded-md bg-[var(--accent)] text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {processing ? "Detecting…" : "Detect form fields"}
                </button>
                {result && (
                  <button
                    type="button"
                    onClick={handleReset}
                    className="w-full px-3 py-2 rounded-md border border-[var(--line)] text-sm text-[var(--ink-2)]"
                  >
                    Reset
                  </button>
                )}
              </div>
            </div>

            {/* Right Panel — Viewer */}
            <div className="flex-1 min-w-0 relative">
              <div className="absolute top-3 right-3 z-10 px-2.5 py-1 text-[10px] font-medium rounded-md bg-gray-900/70 text-white">
                {result ? "With detected fields" : "Original PDF"}
              </div>

              {processing && (
                <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-black/60">
                  <div className="text-center space-y-2">
                    <div className="inline-block w-6 h-6 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
                    <p className="text-sm text-[var(--ink-3)]">
                      Detecting form fields…
                    </p>
                  </div>
                </div>
              )}

              <PdfViewer document={pdfUrl} toolbarItems={TOOLBAR_ITEMS} />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Type-check**

```bash
npx tsc --noEmit
```

Expected: no errors. (Pre-existing Microsoft Edge Tools accessibility warnings in *other* files are fine — only fail on `error TS...` from the new file.)

- [ ] **Step 5: Commit**

```bash
git add public/documents/input_forms_detection.pdf app/python-sdk/form-detection/page.tsx
git commit -m "feat(form-detection): add Python SDK form-field detection demo page"
```

---

## Task 4: End-to-end smoke test + frontend PR

**Repos:** both

- [ ] **Step 1: Run the backend**

In one terminal:

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
.venv/bin/uvicorn app.main:app --port 8080
```

- [ ] **Step 2: Run the frontend**

In another terminal:

```bash
cd /Users/jonaddamsnutrient/SE/code/nutrient-sdk-samples
NEXT_PUBLIC_PYTHON_SDK_API_URL=http://localhost:8080 npm run dev
```

- [ ] **Step 3: Open the page in a browser**

Navigate to `http://localhost:3000/python-sdk/form-detection`.

Verify:
- The Nutrient viewer renders `input_forms_detection.pdf`.
- The left panel says “The sample PDF has 0 form fields…”.
- Clicking **Detect form fields** shows a spinner for ~2–3 seconds.
- After detection: the stats card shows the count and a breakdown; the viewer re-renders with the fielded PDF; the badge in the top-right reads "With detected fields".
- Clicking **Reset** restores the original PDF and clears the stats.
- If you stop the backend and click Detect, the error banner appears with a network-error message (not a silent failure).

- [ ] **Step 4: Stop both servers (Ctrl-C in each terminal).**

- [ ] **Step 5: Push the frontend branch and open a PR**

```bash
cd /Users/jonaddamsnutrient/SE/code/nutrient-sdk-samples
git push -u origin form-field-detection
gh pr create --title "Add Python SDK form-field detection demo" --body "$(cat <<'EOF'
## Summary
- New page at `/python-sdk/form-detection` exercising the `POST /api/forms/detect` endpoint shipped in the python-fast-api repo.
- Loads the Nutrient official sample PDF, runs detection on click, swaps the viewer to the fielded result, and shows a per-type breakdown of detected fields.
- Surfaces backend `detail` strings verbatim (license-gate errors will read "Your license does not include vision_form…").

## Test plan
- [x] `npx tsc --noEmit` — no errors
- [x] Manual E2E against local backend: viewer renders both states, stats card updates, reset works

## Backend PR
Companion PR: <paste the python-fast-api PR URL here>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

The engineer should edit the PR body to paste the backend PR URL from Task 2 Step 7 (or leave a note that the backend PR is forthcoming if it wasn't pushed yet).

---

## Out of scope (do NOT pick up in this plan)

- **Field editing UX in the page.** The Nutrient viewer already supports edit-mode natively when the user toggles it — no in-page editor.
- **Customizing `FormRecognitionSettings`** (confidence threshold, model path, CPU-only flag). The SDK defaults are used. Add tuning later if needed.
- **Download button for the fielded PDF.** Explicitly excluded during brainstorming.
- **User-uploaded PDFs in the frontend.** Backend accepts any PDF; frontend only ships the sample. File-picker can be added later.
- **OCR / scanned-PDF inputs.** Detector quality on those is undefined and not part of this demo.
- **Caching the result.** Every click re-runs detection. Fine for a demo.
- **Updating the existing `list_form_fields` or `fill_form_fields`.** They are correct and untouched.
