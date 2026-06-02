# `PdfAnnotation.get_rect()` returns an opaque native handle integer, not geometry

| Field | Value |
|---|---|
| **Severity** | High |
| **Priority** | High — the geometry accessor is completely unusable |
| **Component** | Python SDK · Annotations API (`PdfAnnotation`) |
| **Affects version** | `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6` (compiled 2026-05-21) |
| **Platform** | macOS 15 (Darwin 25.5.0), ARM64, Apple M4 |
| **Python** | 3.12.13 |
| **Reporter** | Jon Addams (Customer Engineering) |
| **Date** | 2026-06-02 |

## Summary

`PdfAnnotation.get_rect()` returns a raw native object handle (an integer, e.g. `4441456544`)
instead of a usable geometry object. The returned value has no numeric coordinates, no
`x`/`y`/`width`/`height` properties, and is not iterable. Any code that attempts to use the
position or bounds of an annotation — for display, collision detection, export metadata, or
re-positioning — receives a meaningless integer.

## Steps to reproduce

```python
import os
from dotenv import load_dotenv
load_dotenv(".env")
from nutrient_sdk import License, Document, PdfEditor
License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])

with Document.open("tests/fixtures/account-registration-form.pdf") as doc:
    editor = PdfEditor.edit(doc)
    annots = editor.get_page_collection().get_page(1).get_annotation_collection()
    hl = annots.add_highlight(72.0, 700.0, 200.0, 20.0, "QA", "test")
    rect = hl.get_rect()
    print("type:", type(rect))      # <class 'int'>
    print("value:", rect)           # e.g. 4441456544
    print("has x:", hasattr(rect, "x"))        # False
    print("iterable:", hasattr(rect, "__iter__"))  # False
```

## Expected behavior

`get_rect()` should return a geometry object (or tuple/named-tuple) exposing numeric coordinates
matching the values passed to `add_highlight`. At minimum: `x`, `y`, `width`, `height` as
floats, so callers can do `rect.x` or `x, y, w, h = rect`.

## Actual behavior

```
type: <class 'int'>
value: 4441456544
has x: False
iterable: False
```

The return value is a raw pointer/handle integer. It cannot be used for any geometry purpose.

## Impact

- **Annotation export/display:** Any pipeline that reads annotation geometry to overlay on a
  rendered page cannot extract coordinates.
- **Annotation editing:** Moving or resizing an existing annotation requires reading its
  current bounds — impossible with this API.
- **The method is effectively a stub.** There is no workaround that extracts coordinates via
  the Python SDK; the annotation position can only be set (at creation) but never read back.

## Workaround

None within the Nutrient Python SDK. Third-party libraries (PyMuPDF, pdfminer) can read
annotation rectangles from the PDF structure.

## Root cause hypothesis

The Python binding's `get_rect()` method calls the native method and returns the raw .NET
`RectangleF` (or similar) value without marshalling it to a Python object. The binding
generator likely emitted the method but did not add a wrapper to convert the native struct to
a Python type.

## Reproduction artifact

- `tests/sdk/test_annotations.py::test_get_rect_returns_readable_geometry` (xfail)

```python
@defect("SDK-011", "get_rect() returns an opaque native handle int, not geometry")
def test_get_rect_returns_readable_geometry(self, account_form):
    with Document.open(account_form) as doc:
        annots = _annots(PdfEditor.edit(doc))
        a = annots.add_highlight(72.0, 700.0, 200.0, 20.0, "QA", "x")
        rect = a.get_rect()
        # A usable API returns something with numeric coordinates.
        assert hasattr(rect, "__iter__") or hasattr(rect, "x")
```

## Suggested fix

Wrap the native `get_rect()` return value in a Python dataclass or named-tuple with fields
`x`, `y`, `width`, `height` (floats). Alternatively return a `(x, y, width, height)` tuple.
Follow the same pattern as `PdfPage.get_width()` / `get_height()` which correctly marshal
floats.

## Related

- SDK-012: No public annotation indexer — only private `_get_item`/`get_enumerator` — a
  related API completeness gap in the Annotations surface.
