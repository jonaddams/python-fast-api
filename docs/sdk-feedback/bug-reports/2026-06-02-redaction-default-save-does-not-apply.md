# Redaction footgun: default save does not apply redactions — content remains recoverable

| Field | Value |
|---|---|
| **Severity** | High |
| **Priority** | High — security/compliance defect; silent data exposure |
| **Component** | Python SDK · Redaction API (`PdfEditor.save_as`, `PdfSavePreferences`) |
| **Affects version** | `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6` (compiled 2026-05-21) |
| **Platform** | macOS 15 (Darwin 25.5.0), ARM64, Apple M4 |
| **Python** | 3.12.13 |
| **Reporter** | Jon Addams (Customer Engineering) |
| **Date** | 2026-06-02 |

## Summary

When a developer adds a redact annotation and calls `editor.save_as()` **without** explicitly
setting `PdfSavePreferences.APPLY_REDACTIONS`, the saved PDF retains the underlying content —
the redact box is written as a visual annotation only. The text or image under the redaction
box is fully recoverable by any PDF reader or forensic tool that inspects the file's object
stream. There is no warning, no error, and no indication that the save operation was
insufficient. This is a security and compliance footgun that will affect any developer who
does not read the SDK documentation carefully.

## Steps to reproduce

```python
import os, tempfile
from dotenv import load_dotenv
load_dotenv(".env")
from nutrient_sdk import License, Document, PdfEditor, Color
License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])

PDF = "tests/fixtures/account-registration-form.pdf"
out = tempfile.mktemp(suffix=".pdf")

with Document.open(PDF) as doc:
    editor = PdfEditor.edit(doc)
    annots = editor.get_page_collection().get_page(1).get_annotation_collection()
    annots.add_redact(50.0, 50.0, 200.0, 30.0)
    editor.save_as(out)   # <-- NO APPLY_REDACTIONS
    editor.close()

# Reopen and count annotations
with Document.open(out) as doc2:
    editor2 = PdfEditor.edit(doc2)
    count = editor2.get_page_collection().get_page(1).get_annotation_collection().get_count()
    print("annotations after save:", count)  # redact box is still there; content intact
```

For comparison — the correct way to apply redactions:
```python
from nutrient_sdk.pdfsavepreferences import PdfSavePreferences
doc.settings.pdf_settings.save_preferences = PdfSavePreferences.APPLY_REDACTIONS
editor.save_as(out)  # now the content is actually removed
```

## Expected behavior

Either of:
1. **Ideal:** `save_as()` raises a warning or error when redact annotations exist in the
   document but `APPLY_REDACTIONS` is not set, prompting the developer to make an explicit choice.
2. **Acceptable:** Documentation prominently warns that redact annotations are NOT applied by
   default and that `APPLY_REDACTIONS` must be set. Currently this requirement is buried.
3. **Alternative API design:** Make applying redactions the default when redact annotations
   are present; require an explicit opt-out for the annotation-only path.

## Actual behavior

`save_as()` silently saves the file with the redact annotation visible but the underlying
content intact. No warning is raised. The developer has no signal that the save was
incomplete from a compliance standpoint.

## Impact

- **Privacy/compliance risk:** Any developer using the redaction API without knowing about
  `APPLY_REDACTIONS` will produce PDFs that appear redacted but are not. PII, financial data,
  or legally privileged content remains in the file.
- **Silent failure.** There is no indication at the API level that the operation was
  insufficient. The file is valid and the redact box is visible — the failure is invisible
  to a cursory review.
- **Customer trust.** If a customer ships a "redacted" document produced by this API without
  knowing about the flag, they have a data breach.

## Workaround

Always set `PdfSavePreferences.APPLY_REDACTIONS` before calling `save_as()` when redact
annotations are present:

```python
doc.settings.pdf_settings.save_preferences = PdfSavePreferences.APPLY_REDACTIONS
editor.save_as(out)
```

This is the correct path; the bug is that it is not obvious and not enforced.

## Root cause hypothesis

The default save path (likely `PdfSavePreferences.NONE`) preserves all annotations,
including redact annotations, without processing them. `APPLY_REDACTIONS` triggers a
separate native code path that processes the redact annotations and removes the underlying
content. The Python binding correctly exposes both paths but does not guard the dangerous
default.

## Reproduction artifact

- `tests/sdk/test_redaction.py::test_default_save_burns_in_content` (xfail)

```python
@defect("SDK-025", "default NONE save leaves redaction un-applied (content recoverable)")
def test_default_save_burns_in_content(self, account_form):
    out = tempfile.mktemp(suffix=".pdf")
    try:
        with Document.open(account_form) as doc:
            editor = PdfEditor.edit(doc)
            annots = editor.get_page_collection().get_page(1).get_annotation_collection()
            before = annots.get_count()
            annots.add_redact(50.0, 50.0, 200.0, 30.0)
            editor.save_as(out)  # no APPLY_REDACTIONS
            editor.close()
        with Document.open(out) as doc2:
            assert _annots(doc2).get_count() == before  # would mean it was applied
    finally:
        inputs.cleanup(out)
```

## Suggested fix

Raise a `UserWarning` (or a dedicated `NutrientWarning`) from `save_as()` when the document
contains unprocessed redact annotations and `PdfSavePreferences.APPLY_REDACTIONS` is not
active. This gives developers a runtime signal without breaking the existing API.
