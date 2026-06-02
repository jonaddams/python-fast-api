# `PdfPage` rotation is read-only — no `set_rotation()`/`rotate()` API

| Field | Value |
|---|---|
| **Severity** | High |
| **Priority** | High — missing capability despite API surface area implying it exists |
| **Component** | Python SDK · Editor API (`PdfPage`) |
| **Affects version** | `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6` (compiled 2026-05-21) |
| **Platform** | macOS 15 (Darwin 25.5.0), ARM64, Apple M4 |
| **Python** | 3.12.13 |
| **Reporter** | Jon Addams (Customer Engineering) |
| **Date** | 2026-06-02 |

## Summary

`PdfPage` exposes `get_rotation()` to read a page's rotation but provides no corresponding
write method (`set_rotation()`, `rotate()`, or similar). This makes it impossible to
programmatically rotate pages using the Editor API, which is a core document-manipulation
task. The omission is particularly surprising given that the SDK ships a "Document Editor API"
entitlement and `PdfPageCollection` supports add/insert/move/swap/remove operations.

## Steps to reproduce

```python
import os
from dotenv import load_dotenv
load_dotenv(".env")
from nutrient_sdk import License, Document, PdfEditor
License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])

with Document.open("tests/fixtures/account-registration-form.pdf") as doc:
    editor = PdfEditor.edit(doc)
    page = editor.get_page_collection().get_first()
    print("rotation:", page.get_rotation())          # works
    print("has set_rotation:", hasattr(page, "set_rotation"))  # False
    print("has rotate:", hasattr(page, "rotate"))              # False
    print("PdfPage dir:", [m for m in dir(page) if "rotat" in m.lower()])
```

## Expected behavior

`PdfPage` should provide at minimum `set_rotation(degrees: int)` accepting 0/90/180/270,
matching the read side's `get_rotation()`. The pattern of every other getter having a setter
in this SDK strongly implies this should exist.

## Actual behavior

```
rotation: 0
has set_rotation: False
has rotate: False
PdfPage dir: ['get_rotation']
```

No write method exists. Page rotation cannot be changed via the Python SDK.

## Impact

- **Scan ingestion pipelines** that correct orientation for rotated scanned pages cannot use
  the Editor API — they must reach for a third-party PDF library for this one operation.
- **The "Document Editor API" entitlement** advertises page editing. Customers will discover
  this gap immediately when they try the obvious thing.
- **No workaround** within the SDK. External libraries (PyMuPDF, pypdf) can rotate pages.

## Workaround

None within the Nutrient Python SDK. Use an external library (e.g. `pypdf`) to rotate pages,
then open the result with the Nutrient SDK for subsequent operations.

## Root cause hypothesis

The `.NET` core likely exposes `IPdfPage.Rotation` as a gettable property and a separate
setter or mutation method. The Python binding generator may have emitted the getter but
omitted the setter, or the setter may exist on a different interface that is not exposed via
`PdfPage`.

## Reproduction artifact

- `tests/sdk/test_editor.py::test_page_rotation_is_settable` (xfail)

```python
@defect("SDK-007", "PdfPage has no set_rotation()/rotate() despite Document Editor entitlement")
def test_page_rotation_is_settable(self, account_form):
    with Document.open(account_form) as doc:
        page = PdfEditor.edit(doc).get_page_collection().get_first()
        assert hasattr(page, "set_rotation") or hasattr(page, "rotate")
```

## Suggested fix

Expose `PdfPage.set_rotation(degrees: int)` that accepts 0, 90, 180, 270. Raise
`InvalidArgumentException` for values outside that set.
