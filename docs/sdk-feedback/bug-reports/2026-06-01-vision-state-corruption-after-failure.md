# Vision SDK enters process-wide failure state after a single failed call

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Priority** | Critical — blocks production use in long-running processes |
| **Component** | Python SDK · Vision API |
| **Affects version** | `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6` (compiled 2026-05-21) |
| **Platform** | macOS 15 (Darwin 25.5.0), ARM64, Apple M4 |
| **Python** | 3.12.13 |
| **Reporter** | Jon Addams (Customer Engineering) |
| **Date** | 2026-06-01 |

## Summary

Once any call to `Vision.set(doc)` or `Vision.extract_content()` fails with a `VisionException`, **every subsequent Vision call in the same Python process fails with the same exception** — even on known-good inputs that succeed in a fresh process. The SDK appears to retain some failure state (in the native binding) that is never reset. This makes the Vision API unsafe to use in a long-running server process: a single bad upload poisons the SDK for the lifetime of the worker.

This is independent of (but reliably triggered by) the [image-only-PDF defect](./2026-06-01-vision-set-fails-on-image-only-pdfs.md).

## Steps to reproduce

Use any input that triggers a `VisionException` (we use the image-only PDF from the companion bug). Then attempt a Vision call on a known-good input.

```python
import os
from dotenv import load_dotenv
load_dotenv(".env")
from nutrient_sdk import License, Document, Vision, VisionEngine, VisionFeatures

License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])

BROKEN_PDF = "ocr-invoice.pdf"   # scanned invoice — triggers VisionException
GOOD_PNG = "ocr-invoice-page1.png"  # any image known to OCR successfully

def run_ocr(path):
    with Document.open(path) as doc:
        s = doc.get_settings()
        vs = s.get_vision_settings()
        vs.set_engine(VisionEngine.ADAPTIVE_OCR)
        vs.set_features(VisionFeatures.ALL.value - VisionFeatures.FORM.value)
        return Vision.set(doc).extract_content()

# Step 1: trigger the failure
try:
    run_ocr(BROKEN_PDF)
except Exception as e:
    print(f"step 1 (expected fail): {type(e).__name__}: {str(e)[:80]}...")

# Step 2: try the same operation on a known-good input
try:
    result = run_ocr(GOOD_PNG)
    print(f"step 2 (expected OK): {len(result)} chars")
except Exception as e:
    print(f"step 2 (unexpected fail): {type(e).__name__}: {str(e)[:120]}...")
```

## Expected behavior

Step 2 should succeed. The first failure should be scoped to that call; the SDK should be usable for subsequent calls on different documents.

## Actual behavior

```
step 1 (expected fail): VisionException: 1 context(s) failed: VisionDocumentGraphExtraction...
step 2 (unexpected fail): VisionException: 1 context(s) failed: VisionDocumentGraphExtraction: Vision extraction failed for page 1: Completed with 1 failure(s) out of 5 context(s). Failures: InputImage: imageFilePath parameter is required (Error Code: 3024)
```

The error in Step 2 is identical to Step 1 even though the input is a different, known-good file. Running Step 2 alone in a fresh process succeeds.

## Verification of process-wide scope

Verified empirically by isolating the calls in separate processes:

- Process A: run the broken PDF call only → fails as expected
- Process B: run the good PNG call only → succeeds (59 elements)
- Process C: run both in sequence as above → both fail with identical error

The failure of the second call in Process C is the bug.

## Impact

- **Production blocker for long-running servers.** A FastAPI/Flask/Django process exposing Vision-backed endpoints must, after the first bad upload, return errors on *every subsequent request* — until restarted. Customers will see this as an "SDK randomly stopped working" issue with no obvious cause.
- **Defeats per-request retry/fallback patterns.** Application code cannot recover by catching the exception and retrying with different settings or after rendering — the retry runs in the same process and inherits the bad state.
- **Workaround requires process isolation.** The only safe pattern in a long-running server is to invoke Vision in a subprocess that gets discarded after each call (or after each failure). That's a heavyweight workaround for what should be a per-call API.

## Workaround

Two options, both painful:

1. **Subprocess isolation.** Run every Vision call in a fresh `subprocess.run()` invocation. Adds ~200 ms of Python startup + SDK init per request. Loses any benefit from process-level caching.
2. **Pre-validation to avoid the failing input class entirely.** For the known case (image-only PDFs), detect and pre-render before the first Vision call so the bad path is never taken. This is what we did in `app/services/extraction.py:88-101`. It works as long as you can fully characterize the failing inputs upfront — which is fragile.

Neither workaround is acceptable long-term for a server-side SDK.

## Root cause hypothesis

Likely candidates (untested from outside the SDK):

1. **A static or thread-local error flag inside the native binding** is set on first failure and never cleared. Subsequent calls into the Vision graph see the flag and short-circuit to an error before processing the new input.
2. **A native resource (handle, model context, output buffer) is left in an invalid state** by the failed call and reused without reset on subsequent calls.
3. **The error itself is being cached and re-raised** — the second call may not even be executing the OCR pipeline; the native code may be returning the cached error string immediately.

Clue toward (3): the second call's stack trace and error message are byte-identical to the first call's, including the "page 1" reference even when the second input is a single-image PNG, not a PDF with a "page 1".

## Reproduction artifacts

- Broken input: `tests/fixtures/ocr-invoice.pdf` (see companion bug report for file details)
- Good input: any image, e.g. `tests/fixtures/input_ocr_multiple_languages.png`

## Suggested fix

Whichever native state survives a failed Vision call needs to be reset before the next call. Ideally the SDK should treat each `Vision.set()` / `extract_content()` invocation as fully independent — no shared mutable state, or at minimum a `Vision.reset()` API the customer can call after catching an exception.

## Related

- Companion defect: [Vision.set() fails on image-only PDFs](./2026-06-01-vision-set-fails-on-image-only-pdfs.md). That defect is the simplest way to reproduce this one but is not the only path — any input that causes Vision to throw should be sufficient to demonstrate the state corruption.
