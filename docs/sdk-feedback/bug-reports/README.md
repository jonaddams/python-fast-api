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

The two 2026-06-01 reports are companions — the first is the easiest reliable trigger for the second, but the second is independent.

## Distinct from `docs/sdk-feedback/`

The parent `docs/sdk-feedback/` folder collects broader quality observations and design feedback (the Claude vs ICR comparison, AiAugmenter no-op findings, recommendations on `Vision.transcribe()`, etc.) — appropriate for sharing as a discussion artifact with the SDK team, but not formatted as actionable defects.

This `bug-reports/` subfolder is the opposite: each item is a specific, reproducible defect with enough scaffolding that a JIRA ticket can be opened directly from the file.
