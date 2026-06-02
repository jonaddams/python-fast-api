# `*Settings` objects for exporters are orphaned — no Python API attaches them

| Field | Value |
|---|---|
| **Severity** | High |
| **Priority** | High — advertised configuration surface is completely unreachable |
| **Component** | Python SDK · Exporters API (`HtmlExporter`, `PdfExporter`, `WordExporter`, etc.) |
| **Affects version** | `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6` (compiled 2026-05-21) |
| **Platform** | macOS 15 (Darwin 25.5.0), ARM64, Apple M4 |
| **Python** | 3.12.13 |
| **Reporter** | Jon Addams (Customer Engineering) |
| **Date** | 2026-06-02 |

## Summary

The SDK exports several `*Settings` classes (`HtmlExportSettings`, `PdfExportSettings`,
`WordExportSettings`, `MarkdownExportSettings`, `PresentationSettings`, etc.) that appear to
control exporter behavior. However, none of the exporter classes (`HtmlExporter`,
`PdfExporter`, `WordExporter`, `MarkdownExporter`) expose a `set_settings()` method or any
other mechanism to attach a settings object. The settings classes are fully instantiable but
completely disconnected from the export pipeline — they can be created but their values are
never used.

## Steps to reproduce

```python
import os
from dotenv import load_dotenv
load_dotenv(".env")
from nutrient_sdk import License, HtmlExporter
import nutrient_sdk
License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])

exp = HtmlExporter()
print("has set_settings:", hasattr(exp, "set_settings"))   # False
print("HtmlExporter dir:", [m for m in dir(exp) if "setting" in m.lower()])  # []
# Check if HtmlExportSettings even exists
print("HtmlExportSettings:", hasattr(nutrient_sdk, "HtmlExportSettings"))
exp.close()
```

## Expected behavior

Each exporter should accept its matching settings object:

```python
from nutrient_sdk import HtmlExporter, HtmlExportSettings
settings = HtmlExportSettings()
settings.set_some_option(...)
exporter = HtmlExporter()
exporter.set_settings(settings)   # should work
doc.export(out, exporter)
```

Or alternatively, settings should be passed to the exporter constructor or to `doc.export()`.

## Actual behavior

```
has set_settings: False
HtmlExporter dir: []
```

No attachment point exists. The `*Settings` classes are dead code from the Python caller's
perspective.

## Impact

- **Export customization is impossible.** Any option that requires an export settings object
  (page range, image quality, compression settings, HTML embedding options, etc.) cannot be
  configured via the Python SDK.
- **The `*Settings` classes are misleading.** Developers who discover them will spend time
  trying to find the attachment point that does not exist.
- **Documentation gap compounds the issue.** If the docs mention settings objects in code
  samples, those samples will silently do nothing.

## Workaround

None. Exporter customization beyond what can be configured on the `Document` itself is not
possible through the Python SDK at this time.

## Root cause hypothesis

The exporter binding was generated from a native interface that includes settings, but the
Python binding generator emitted the settings classes without also emitting the
`set_settings` method on the exporter classes (or the native method was added to the
interface after the binding was generated).

## Reproduction artifact

- `tests/sdk/test_exporters.py::test_exporter_accepts_settings` (xfail)

```python
@defect("SDK-029", "no Python API attaches a *Settings object to any exporter")
def test_exporter_accepts_settings(self):
    exp = HtmlExporter()
    try:
        assert hasattr(exp, "set_settings") or "settings" in dir(exp)
    finally:
        exp.close()
```

## Suggested fix

Add `set_settings(settings: T)` to each exporter class where `T` is the corresponding
settings type (`HtmlExportSettings`, `PdfExportSettings`, etc.). If the native interface
already supports this, it is purely a binding generation gap.

## Related

- SDK-030: `ImageExportFormat` only exposes `TIFF` despite advertising PNG/JPEG/TIFF/BMP —
  a related exporter API completeness gap.
- SDK-033: `PresentationSettings` has zero properties — the settings-class-exists-but-is-
  empty pattern seen throughout the Exporters area.
