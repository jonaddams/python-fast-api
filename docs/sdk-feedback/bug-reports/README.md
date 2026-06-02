# SDK Bug Reports (JIRA-ready)

JIRA-ticket-ready writeups of specific defects discovered while building the demo. Each report is a standalone document that can be copy-pasted (or attached) into a JIRA ticket for the SDK team. They follow a consistent format:

- Severity / priority / component / version metadata
- One-paragraph summary
- Steps to reproduce with runnable code
- Expected vs. actual behavior with full error messages
- Verification details (other files tested, isolated reproduction)
- Customer-facing impact statement
- Workaround (if known) with explicit tradeoffs
- Root cause hypothesis
- Reproduction artifacts (committed to this repo where redistributable)
- Suggested fix
- Cross-links to related reports

## Reports

| Date | Title | Severity |
|---|---|---|
| 2026-06-01 | [`Vision.set()` fails on image-only PDFs](./2026-06-01-vision-set-fails-on-image-only-pdfs.md) | High |
| 2026-06-01 | [Vision SDK enters process-wide failure state after a single failed call](./2026-06-01-vision-state-corruption-after-failure.md) | Critical |
| 2026-06-02 | [Corrupt/empty/wrong-magic file opens with `InitializationError(1006)` instead of `DocumentError`](./2026-06-02-corrupt-file-surfaces-wrong-exception.md) | High |
| 2026-06-02 | [`PdfPage` rotation is read-only — no `set_rotation()`/`rotate()` API](./2026-06-02-pdfpage-rotation-read-only.md) | High |
| 2026-06-02 | [`PdfAnnotation.get_rect()` returns an opaque native handle integer, not geometry](./2026-06-02-annotation-get-rect-returns-opaque-handle.md) | High |
| 2026-06-02 | [Form-field accessors always return base `PdfFormField`, never the typed subtype](./2026-06-02-form-field-collection-returns-base-type.md) | High |
| 2026-06-02 | [Redaction footgun: default save does not apply redactions — content remains recoverable](./2026-06-02-redaction-default-save-does-not-apply.md) | High |
| 2026-06-02 | [`*Settings` objects for exporters are orphaned — no Python API attaches them](./2026-06-02-exporter-settings-not-attachable.md) | High |

The two 2026-06-01 reports are companions — the first is the easiest reliable trigger for the second, but the second is independent.

The six 2026-06-02 reports are stubs from the `sdk-defect-hunting-tests` branch; each corresponds to a confirmed xfail defect in `tests/sdk/` and maps to a registry entry in `../DEFECTS.md`.

## Distinct from `docs/sdk-feedback/`

The parent `docs/sdk-feedback/` folder collects broader quality observations and design feedback (the Claude vs ICR comparison, AiAugmenter no-op findings, recommendations on `Vision.transcribe()`, etc.) — appropriate for sharing as a discussion artifact with the SDK team, but not formatted as actionable defects.

This `bug-reports/` subfolder is the opposite: each item is a specific, reproducible defect with enough scaffolding that a JIRA ticket can be opened directly from the file.
