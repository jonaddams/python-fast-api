# Corrupt/empty/wrong-magic file opens with `InitializationError(1006)` instead of `DocumentError`

| Field | Value |
|---|---|
| **Severity** | High |
| **Priority** | High — misleading exception type complicates error handling |
| **Component** | Python SDK · Document API / Conversion API / Editor API |
| **Affects version** | `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6` (compiled 2026-05-21) |
| **Platform** | macOS 15 (Darwin 25.5.0), ARM64, Apple M4 |
| **Python** | 3.12.13 |
| **Reporter** | Jon Addams (Customer Engineering) |
| **Date** | 2026-06-02 |

## Summary

When `Document.open()` is given a file with invalid or unexpected content (wrong magic bytes,
empty file, truncated PDF, empty `.docx`), the SDK raises
`InitializationError('Arg_NullReferenceException', error code 1006)` — a generic internal
initialization failure — instead of the semantically appropriate `DocumentError`. The same
wrong class also surfaces from `PdfEditor.edit()` on a bad document and from
`doc.export(path, None)`. Application code that catches `DocumentError` to handle user
upload errors will silently miss these cases, causing unhandled exceptions in production.

## Steps to reproduce

```python
import os, tempfile
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(".env")
from nutrient_sdk import License, Document
License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])

# Case 1: wrong magic bytes
path = tempfile.mktemp(suffix=".pdf")
Path(path).write_bytes(b"NOT A PDF FILE")
try:
    Document.open(path)
except Exception as e:
    print(type(e).__name__, repr(str(e)[:80]))

# Case 2: empty file
path2 = tempfile.mktemp(suffix=".pdf")
Path(path2).write_bytes(b"")
try:
    Document.open(path2)
except Exception as e:
    print(type(e).__name__, repr(str(e)[:80]))
```

## Expected behavior

Both cases should raise `nutrient_sdk.DocumentError` (or a direct subclass thereof). A caller
handling bad file uploads should be able to write `except DocumentError` and catch all invalid
document inputs.

## Actual behavior

```
InitializationError: Arg_NullReferenceException (Error Code: 1006)
InitializationError: Arg_NullReferenceException (Error Code: 1006)
```

`InitializationError` is a generic SDK bootstrap failure, not a domain-level document error.
Application code using `except DocumentError` will not catch it.

## Impact

- **Upload validation pipelines** that catch `DocumentError` for user-facing "invalid file"
  messages will not catch `InitializationError`. Users see a 500 instead of a 400.
- **The same wrong type** surfaces from `PdfEditor.edit()` on an already-corrupted document
  and from `doc.export(path, None)` — so the problem is not isolated to `Document.open`.

## Workaround

Catch the broader `nutrient_sdk.NutrientException` as a fallback, or specifically also catch
`InitializationError`. Not ideal because `InitializationError` is also raised for genuine
SDK configuration problems (missing license, native library load failure) which should be
treated differently from bad user input.

## Root cause hypothesis

`Document.open()` likely delegates to a native method that raises a generic .NET
`NullReferenceException` when it dereferences a handle that could not be populated from an
invalid file. The Python binding wraps this as `InitializationError` without a layer that
maps "open failed because of bad content" to `DocumentError`.

## Reproduction artifacts

- `tests/sdk/_support/inputs.py` — `wrong_magic()` and `empty_file()` helpers that create
  these inputs in a temp file.
- `tests/sdk/test_document.py::test_open_wrong_magic_is_documenterror` (xfail)
- `tests/sdk/test_document.py::test_open_empty_file_is_documenterror` (xfail)
- `tests/sdk/test_conversion.py::test_empty_office_file_is_typed` (xfail)
- `tests/sdk/test_editor.py::test_edit_corrupt_pdf_is_documenterror` (xfail)

## Suggested fix

In the Python binding's `Document.open()` path, catch the native `InitializationError`
variant that arises from file-open failures and re-raise it as `DocumentError`. The heuristic
could be: if the path exists and is readable but the SDK cannot parse it, it is a document
error; if the SDK itself failed to initialize, it is an initialization error.

## Related

- SDK-001: `Document.open(None)` raises bare `TypeError` — a related input-validation gap.
- SDK-006: `export_as_image(None)` surfaces `InitializationError(1002)` instead of a
  null-argument exception — same pattern, different method.
