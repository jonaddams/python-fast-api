# Vision.set() fails on image-only PDFs with "imageFilePath parameter is required"

| Field | Value |
|---|---|
| **Severity** | High |
| **Priority** | High — blocks OCR on scanned PDFs |
| **Component** | Python SDK · Vision API |
| **Affects version** | `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6` (compiled 2026-05-21) |
| **Platform** | macOS 15 (Darwin 25.5.0), ARM64, Apple M4 |
| **Python** | 3.12.13 |
| **Reporter** | Jon Addams (Customer Engineering) |
| **Date** | 2026-06-01 |

## Summary

`Vision.extract_content()` (and `Vision.set()`, depending on the call path) fails with `VisionException: InputImage: imageFilePath parameter is required (Error Code: 3024)` when the input is a PDF whose page content is a single embedded raster image (e.g. a scanned invoice). Native-text PDFs work; image-only PDFs do not. Other SDK operations on the same file — including `Document.export_as_image()` — succeed, so the file itself is valid; the limitation is specifically in the Vision pipeline's `InputImage` sub-stage.

## Steps to reproduce

Tested against `tests/fixtures/ocr-invoice.pdf` in this repository — a 9.4 MB single-page scanned invoice (PDF 1.4, zip-deflate encoded, 1 page, 1 embedded image, no native text).

```python
import os
from dotenv import load_dotenv
load_dotenv(".env")
from nutrient_sdk import License, Document, Vision, VisionEngine, VisionFeatures

License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])

PDF = "ocr-invoice.pdf"  # scanned single-page invoice

with Document.open(PDF) as doc:
    settings = doc.get_settings()
    vision_settings = settings.get_vision_settings()
    vision_settings.set_engine(VisionEngine.ADAPTIVE_OCR)
    vision_settings.set_features(VisionFeatures.ALL.value - VisionFeatures.FORM.value)
    vision = Vision.set(doc)
    content = vision.extract_content()  # raises
```

## Expected behavior

`extract_content()` returns a JSON string describing the detected text regions of the rasterized page. The Vision pipeline should handle image-only PDFs the same way it handles a standalone PNG — it should rasterize the page internally and proceed to OCR.

## Actual behavior

```
nutrient_sdk.visionexception.VisionException: 1 context(s) failed:
VisionDocumentGraphExtraction: Vision extraction failed for page 1:
Completed with 1 failure(s) out of 5 context(s).
Failures: InputImage: imageFilePath parameter is required
(Error Code: 3024) [Source: Vision]
```

Depending on timing/state the same error is also raised at `Vision.set(doc)` (Source: `Set`) rather than `extract_content()` (Source: `Vision`).

## Reproduction confirms it is page-content-dependent, not file-corruption

Run the same code against three PDFs:

| File | Page content | Result |
|---|---|---|
| `tests/fixtures/account-registration-form.pdf` | Native text + form fields | OK — 9 elements extracted |
| `tests/fixtures/input_forms_detection.pdf` | Single embedded image | FAIL — same error |
| `tests/fixtures/ocr-invoice.pdf` (this report) | Single embedded image | FAIL — same error |

So the SDK can read text-native PDFs through Vision. It cannot read image-only PDFs.

## Workaround

Render the PDF's first page to a PNG with `Document.export_as_image()`, then call Vision on the PNG:

```python
import tempfile
with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
    rendered = tmp.name
with Document.open(PDF) as doc:
    doc.export_as_image(rendered)
with Document.open(rendered) as doc:
    settings = doc.get_settings()
    vision_settings = settings.get_vision_settings()
    vision_settings.set_engine(VisionEngine.ADAPTIVE_OCR)
    vision_settings.set_features(VisionFeatures.ALL.value - VisionFeatures.FORM.value)
    content = Vision.set(doc).extract_content()  # works — 59 elements
```

This proves the underlying OCR pipeline functions; the gap is specifically that the Vision pipeline doesn't transparently rasterize image-only PDF pages.

Note: this workaround loses multi-page support — `export_as_image()` writes a single image. A complete fix on the customer side would need to iterate pages.

## Impact

- **Customer-facing demos and quickstarts** that promise "OCR your documents" fail on the canonical use case: a scanned invoice or receipt. Customers will encounter this immediately on their own files.
- **Anyone routing arbitrary user uploads through `Vision.extract_content()`** will see intermittent 500-class errors that look like an SDK crash but are this defect. Combined with the companion bug ([state corruption after failure](./2026-06-01-vision-state-corruption-after-failure.md)), a single bad upload can break the SDK for the rest of the process lifetime.

## Root cause hypothesis

The error string suggests the Vision pipeline's `InputImage` sub-stage expects a filesystem path to a raster image and isn't receiving one when the input is a PDF. Either:

1. The PDF→raster rasterizer that should feed `InputImage` is silently producing an empty/missing path on image-only pages; or
2. The native `Vision.set` code path takes the input-document path directly without ever invoking the rasterizer when the page has no native text content; or
3. There's a feature/engine-specific gate that decides to skip rasterization based on a heuristic that fails on these PDFs.

Since `Document.export_as_image()` on the SAME file produces a valid PNG (verified — 6.7 MB output), the underlying rasterization capability is present in the SDK; it's just not being invoked correctly from the Vision path.

## Reproduction artifact

`tests/fixtures/ocr-invoice.pdf` — 9,392,622 bytes, PDF 1.4, single page, single embedded image.

```
$ qpdf --json-output=2 --json-key=pages ocr-invoice.pdf | jq '.pages | length, .pages[0].images | length'
1
1
```

Backend regression test that exercises the workaround:
`tests/test_extraction.py::test_ocr_endpoint_extracts_image_only_pdf`

## Suggested fix

Have the Vision pipeline rasterize image-only PDF pages internally (via the same code path `Document.export_as_image()` uses) before handing off to `InputImage`. The customer should not need to pre-render.

## Related

- Companion defect: [Vision SDK enters process-wide failure state after a single failed call](./2026-06-01-vision-state-corruption-after-failure.md)
