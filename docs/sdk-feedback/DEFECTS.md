# Nutrient Python SDK — Defect Registry

Living log of defects found by `tests/sdk/`. Status: `open` (found, not filed),
`filed` (JIRA ticket exists, link it), `fixed` (SDK corrected — remove the xfail).

| ID | Area | Symptom | Severity | Status |
|----|------|---------|----------|--------|
| SDK-001 | Document | `Document.open(None)` / `open(bytes)` raises bare Python `TypeError`, not a typed `NutrientArgumentNullException` | med | open |
| SDK-002 | Document/Conversion/Editor/Forms | Corrupt/empty/wrong-magic file surfaces as `InitializationError('Arg_NullReferenceException', 1006)` instead of `DocumentError` | high | open |
| SDK-003 | Document/Vision/Exporters | Process-wide native state corruption: one failed call poisons all later calls in the process (reproduced for Vision calls AND exporter export() with bad path — subsequent Document.open raises IOError with the stale bad path; NOT reproduced at Document.open level) | critical | filed |
| SDK-004 | Document/Conversion/Signing/Exporters | Use-after-close raises bare Python `ValueError`, not typed `InvalidStateException` | med | open |
| SDK-005 | Document | `export_as_image` ignores file extension for format selection | low | open |
| SDK-006 | Document | `export_as_image(None)` raises `InitializationError(EmptyString,1002)` not a null-arg exception | low | open |
| SDK-007 | Editor | `PdfPage` rotation is read-only — no `set_rotation()`/`rotate()` despite "Document Editor API" entitlement | high | open |
| SDK-008 | Editor/Forms/Redaction | `PdfEditor.edit()` twice on one Document does not raise `AlreadyOpenForEditionException` (which exists) | med | open |
| SDK-009 | Editor | `pages.add(width=-5, height=-5)` raises `IndexOutOfBoundsException` instead of `InvalidArgumentException` | med | open |
| SDK-010 | Editor | Editor use-after-close raises `IndexOutOfBoundsException` instead of `InvalidStateException` | med | open |
| SDK-011 | Annotations | `PdfAnnotation.get_rect()` returns an opaque native handle int, not geometry | high | open |
| SDK-012 | Annotations | No public annotation indexer; only private `_get_item` / `get_enumerator` | med | open |
| SDK-013 | Forms/Document | Form-field collection AND `PdfPageCollection.__getitem__` raise builtin `IndexError` instead of a `NutrientException` subclass (while `PdfPageCollection.get_page()` is correctly typed) | med | open |
| SDK-014 | Forms | `find_by_full_name` returns `None` silently for a missing field | med | open |
| SDK-015 | Forms | `set_value(None)` silently accepted on a text field | med | open |
| SDK-016 | Forms | `set_value('bogus')` on a radio/combo field accepted without option validation | med | open |
| SDK-017 | Forms | `collection[i]` / `find_by_full_name` always return base `PdfFormField`, never the typed subtype | high | open |
| SDK-018 | Forms | `FormRecognitionSettings.set_confidence_threshold` accepts out-of-[0,1] values unvalidated | med | open |
| SDK-019 | Signing | `get_hash_algorithm()` returns raw int, not `SignatureHashAlgorithm` (asymmetric round-trip) | low | open |
| SDK-020 | Signing | `set_hash_algorithm('SHA256')` raises raw ctypes `ArgumentError`, not a typed exception | med | open |
| SDK-021 | Signing | `Signature` use-after-close raises bare Python `ValueError` | med | open |
| SDK-022 | Signing | Wrong password & missing cert both raise generic `SdkException` 3025 (no dedicated cert exception) | med | open |
| SDK-023 | Signing | `sign(doc, None, opts)` raises `InitializationError(1002)` not a null-arg exception | low | open |
| SDK-024 | Redaction/Annotations | `add_redact`/markup factories accept negative/NaN/inf geometry without validation | med | open |
| SDK-025 | Redaction | APPLY_REDACTIONS footgun: default `NONE` leaves underlying content recoverable | high | open |
| SDK-026 | Vision | Image-only/scanned PDF fails at `InputImage` stage with truncated message | high | filed |
| SDK-027 | Vision | VLM-unavailable only detectable by string-matching the message; no typed exception | med | open |
| SDK-028 | Vision | `extraction.py` strips `VisionFeatures.FORM` assuming unlicensed, but `vision_form` is now licensed in 1.0.6 (stale) | low | open |
| SDK-029 | Exporters | Orphaned `*Settings`: no Python API attaches settings to any exporter | high | open |
| SDK-030 | Exporters | `ImageExportFormat` exposes only `TIFF` despite docstring claiming PNG/JPEG/TIFF/BMP | med | open |
| SDK-031 | Exporters | `export()` doesn't guard a closed exporter — raises opaque `InitializationError(1006)` instead of a clean `ValueError` (confirmed; no native crash on macOS 1.0.6 but wrong exception type) | med | open |
| SDK-032 | Conversion | `ConversionSettings.set_timeout_milliseconds(-1)` accepted unvalidated | low | open |
| SDK-033 | Conversion/Exporters | `PresentationSettings` has zero properties (PDF→PPTX tuning incomplete) | low | open |
| SDK-034 | Signing | macOS fork-safety: once nutrient_sdk is loaded in a process, calling sign() in a fork()ed child aborts (SIGABRT, Security.framework/objc). Other SDK ops survive fork; only signing is affected. Use a spawned subprocess to sign. | med | open |
| SDK-035 | Vision | macOS fork-safety: `Vision.describe()` with a VLM provider (CLAUDE) crashes with SIGSEGV (signal 11) in a fork()ed child. Works correctly in a spawned subprocess. Same root as SDK-034; VLM path triggers an additional unsafe native routine. | high | open |
