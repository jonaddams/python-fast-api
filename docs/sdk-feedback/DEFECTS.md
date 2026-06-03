# Nutrient Python SDK — Defect Registry

Living log of defects found by `tests/sdk/`. Status: `open` (found, not filed),
`filed` (JIRA ticket exists, link it), `fixed` (SDK corrected — remove the xfail).

**Summary:** 36 SDK defects catalogued (SDK-001 through SDK-037, excluding SDK-028 which was
reclassified as a code-cleanup). 30 are confirmed by automated xfail tests in `tests/sdk/`; 6
are documented-only (SDK-005, SDK-012, SDK-019, SDK-033, SDK-036, SDK-037). SDK-028 is reclassified as
`code-cleanup (not SDK)` — `app/services/extraction.py` strips `VisionFeatures.FORM` assuming
unlicensed, but `vision_form` is licensed; the fix is to drop the FORM opt-out in extraction.py.
The suite is run via `make test-sdk` (`pytest tests/sdk/ --forked -v -rxX`) and currently tallies
**38 passed / 38 xfailed / 2 skipped / 0 failed / 0 xpassed**. The `--forked` flag is required
because SDK-003 (process-wide state corruption) and the SDK-034/035 macOS fork-safety class make
sequential runs in a single process unreliable. The two fork-safety reproductions
(test_signing.py::test_sign_in_forked_child_aborts, test_vision.py::test_describe_returns_text)
deliberately crash a child process, which pops a macOS "Python quit unexpectedly" dialog on
every run — they are skipped by default and run with `SDK_FORK_CRASH_TESTS=1 make test-sdk`
(tally then: 39 passed / 39 xfailed).

| ID | Area | Symptom | Severity | Status | Test |
|----|------|---------|----------|--------|------|
| SDK-001 | Document | `Document.open(None)` / `open(bytes)` raises bare Python `TypeError`, not a typed `NutrientArgumentNullException` | med | open | test_document.py::test_open_none_is_typed, test_open_bytes_is_typed |
| SDK-002 | Document/Conversion/Editor/Forms | Corrupt/empty/wrong-magic file surfaces as `InitializationError('Arg_NullReferenceException', 1006)` instead of `DocumentError` | high | filed ([NAPY-9](https://nutrient.atlassian.net/browse/NAPY-9)) | test_document.py::test_open_wrong_magic_is_documenterror, test_open_empty_file_is_documenterror; test_conversion.py::test_empty_office_file_is_typed; test_editor.py::test_edit_corrupt_pdf_is_documenterror; test_exporters.py::test_none_exporter_is_typed |
| SDK-003 | Document/Vision/Exporters | Process-wide native state corruption: one failed call poisons all later calls in the process (reproduced for Vision calls AND exporter export() with bad path — subsequent Document.open raises IOError with the stale bad path; NOT reproduced at Document.open level) | critical | filed ([NAPY-7](https://nutrient.atlassian.net/browse/NAPY-7)) | test_vision.py::test_failed_vision_does_not_poison_next; test_exporters.py::test_failed_export_does_not_leak_state |
| SDK-004 | Document/Conversion/Signing/Exporters | Use-after-close raises bare Python `ValueError`, not typed `InvalidStateException` | med | open | test_document.py::test_use_after_close_is_typed |
| SDK-005 | Document | `export_as_image` ignores file extension for format selection — writes TIFF bytes into a `.png`-named file | low | filed ([NAPY-16](https://nutrient.atlassian.net/browse/NAPY-16), combined with SDK-030) | documented-only |
| SDK-006 | Document | `export_as_image(None)` raises `InitializationError(EmptyString,1002)` not a null-arg exception | low | open | test_document.py::test_export_none_path_is_null_arg |
| SDK-007 | Editor | `PdfPage` rotation is read-only — no `set_rotation()`/`rotate()` despite "Document Editor API" entitlement | high | filed ([NAPY-10](https://nutrient.atlassian.net/browse/NAPY-10)) | test_editor.py::test_page_rotation_is_settable |
| SDK-008 | Editor/Forms/Redaction | `PdfEditor.edit()` twice on one Document does not raise `AlreadyOpenForEditionException` (which exists) | med | open | test_editor.py::test_concurrent_edit_is_guarded |
| SDK-009 | Editor | `pages.add(width=-5, height=-5)` raises `IndexOutOfBoundsException` instead of `InvalidArgumentException` | med | open | test_editor.py::test_add_negative_dims_is_invalid_arg |
| SDK-010 | Editor | Editor use-after-close raises `IndexOutOfBoundsException` instead of `InvalidStateException` | med | open | test_editor.py::test_editor_use_after_close_is_state_error |
| SDK-011 | Annotations | `PdfAnnotation.get_rect()` returns an opaque native handle int, not geometry | high | filed ([NAPY-11](https://nutrient.atlassian.net/browse/NAPY-11)) | test_annotations.py::test_get_rect_returns_readable_geometry |
| SDK-012 | Annotations | No public annotation indexer; only private `_get_item` / `get_enumerator` | med | open | documented-only |
| SDK-013 | Forms/Document | Form-field collection AND `PdfPageCollection.__getitem__` raise builtin `IndexError` instead of a `NutrientException` subclass (while `PdfPageCollection.get_page()` is correctly typed) | med | open | test_forms.py::test_index_out_of_range_is_typed; test_document.py::test_getitem_out_of_range_is_typed |
| SDK-014 | Forms | `find_by_full_name` returns `None` silently for a missing field | med | open | test_forms.py::test_missing_field_lookup_raises |
| SDK-015 | Forms | `set_value(None)` silently accepted on a text field | med | open | test_forms.py::test_set_value_none_rejected |
| SDK-016 | Forms | `set_value('bogus')` on a radio/combo field accepted without option validation | med | open | test_forms.py::test_invalid_option_rejected |
| SDK-017 | Forms | `collection[i]` / `find_by_full_name` always return base `PdfFormField`, never the typed subtype | high | filed ([NAPY-12](https://nutrient.atlassian.net/browse/NAPY-12)) | test_forms.py::test_field_is_typed_subtype |
| SDK-018 | Forms | `FormRecognitionSettings.set_confidence_threshold` accepts out-of-[0,1] values unvalidated | med | open | test_forms.py::test_confidence_out_of_range_rejected |
| SDK-019 | Signing | `get_hash_algorithm()` returns raw int, not `SignatureHashAlgorithm` (asymmetric round-trip) | low | open | documented-only |
| SDK-020 | Signing | `set_hash_algorithm('SHA256')` raises raw ctypes `ArgumentError`, not a typed exception | med | open | test_signing.py::test_hash_algorithm_bad_type_is_typed |
| SDK-021 | Signing | `Signature` use-after-close raises bare Python `ValueError` | med | open | test_signing.py::test_use_after_close_is_typed |
| SDK-022 | Signing | Wrong password & missing cert both raise generic `SdkException` 3025 (no dedicated cert exception) | med | open | test_signing.py::test_nonexistent_cert_is_filenotfound |
| SDK-023 | Signing | `sign(doc, None, opts)` raises `InitializationError(1002)` not a null-arg exception | low | open | test_signing.py::test_none_output_path_is_null_arg |
| SDK-024 | Redaction/Annotations | `add_redact`/markup factories accept negative/NaN/inf geometry without validation | med | open | test_annotations.py::test_negative_geometry_rejected, test_non_finite_coords_rejected; test_redaction.py::test_negative_redact_geometry_rejected |
| SDK-025 | Redaction | APPLY_REDACTIONS footgun: default `NONE` leaves underlying content recoverable | high | filed ([NAPY-13](https://nutrient.atlassian.net/browse/NAPY-13)) | test_redaction.py::test_default_save_burns_in_content |
| SDK-026 | Vision | Image-only/scanned PDF fails at `InputImage` stage with truncated message | high | filed ([NAPY-8](https://nutrient.atlassian.net/browse/NAPY-8)) | test_vision.py::test_scanned_pdf_extracts_or_raises_clean |
| SDK-027 | Vision | Out-of-range/undefined `VisionFeatures` bitmask (e.g. `set_features(999)`) is silently accepted, not rejected with `InvalidSettingsException`/`InvalidArgumentException` | med | open | test_vision.py::test_bad_features_bitmask_rejected |
| SDK-028 | Code-cleanup (not SDK) | NOT an SDK defect — `app/services/extraction.py` stripped `VisionFeatures.FORM` assuming unlicensed, but `vision_form` IS licensed in 1.0.6. Verified FORM works (test_form_feature_is_licensed, passing). **FIXED 2026-06-03:** the FORM opt-out was removed; `_LICENSED_VISION_FEATURES` is now the full set (guarded by test_extraction.py::test_licensed_vision_features_is_full_set). | low | code-cleanup | test_vision.py::test_form_feature_is_licensed (passing regression guard) |
| SDK-029 | Exporters | Orphaned `*Settings`: no Python API attaches settings to any exporter | high | filed ([NAPY-14](https://nutrient.atlassian.net/browse/NAPY-14)) | test_exporters.py::test_exporter_accepts_settings |
| SDK-030 | Exporters | `ImageExportFormat` exposes only `TIFF` despite docstring claiming PNG/JPEG/TIFF/BMP; with SDK-005 this breaks VLM provider interop (OpenAI rejects the TIFF upload — see PR #15) | med | filed ([NAPY-16](https://nutrient.atlassian.net/browse/NAPY-16)) | test_exporters.py::test_image_export_formats_available |
| SDK-031 | Exporters | `export()` doesn't guard a closed exporter — raises opaque `InitializationError(1006)` instead of a clean `ValueError` (confirmed; no native crash on macOS 1.0.6 but wrong exception type) | med | open | test_exporters.py::test_export_with_closed_exporter_is_typed |
| SDK-032 | Conversion | `ConversionSettings.set_timeout_milliseconds(-1)` accepted unvalidated | low | open | test_conversion.py::test_negative_timeout_rejected |
| SDK-033 | Conversion/Exporters | `PresentationSettings` has zero properties (PDF→PPTX tuning incomplete) | low | open | documented-only |
| SDK-034 | Signing | macOS fork-safety: once nutrient_sdk is loaded in a process, calling sign() in a fork()ed child aborts (SIGABRT, Security.framework/objc). Other SDK ops survive fork; only signing is affected. Use a spawned subprocess to sign. See also SDK-035. | med | open | test_signing.py::test_sign_in_forked_child_aborts (passing direct-assertion test, not xfail) |
| SDK-035 | Vision | macOS fork-safety: `Vision.describe()` with a VLM provider (CLAUDE) crashes with SIGSEGV (signal 11) in a fork()ed child. Works correctly in a spawned subprocess. Same root cause as SDK-034. See also SDK-034. | med | open | test_vision.py::test_describe_returns_text |
| SDK-036 | Vision | VLM-unavailable (no local server / unreachable provider) is only detectable by string-matching the exception message (`localhost:1234` / `Connection refused`); no dedicated typed exception. `extraction.py` hand-rolls `LocalVlmUnavailable` around the string match. | med | open | documented-only |
| SDK-037 | Vision | `VisionFeatures.KEY_VALUE_REGION` is a no-op: licensed and accepted, but output contains zero key/value-tagged elements on key-value-rich documents (verified live 2026-06-03 — 20 elements on an invoice, all paragraph/table/picture). `extraction.py` `extract_fields()` pairs it with a schema-driven `describe()` as the workaround. | high | filed ([NAPY-15](https://nutrient.atlassian.net/browse/NAPY-15)) | documented-only (live repro in bug report; no automated test — would need a live VLM call under --forked, see SDK-035 fork hostility) |

**SDK-034/035 note:** The SDK is not fork-safe on macOS — operations using Security.framework
(signing) or the VLM path (describe) abort in a fork()ed child once nutrient_sdk is loaded;
spawn a subprocess instead. Other operations survive fork.

---

## Coverage legend

- **confirmed** — an xfail test exists; the suite asserts the defect is present every run.
- **documented-only** — no dedicated test; defect observed and recorded but not automated.
  These six lack coverage: SDK-005, SDK-012, SDK-019, SDK-033, SDK-036, SDK-037.
- **code-cleanup** — reclassified as an app-code issue, not an SDK defect (SDK-028).
