# `VisionFeatures.KEY_VALUE_REGION` is a no-op — licensed feature produces no key/value-tagged elements

| Field | Value |
|---|---|
| **Severity** | High |
| **Priority** | High — a licensed, advertised feature produces no output |
| **Component** | Python SDK · Vision API (`VisionFeatures.KEY_VALUE_REGION`) |
| **Affects version** | `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6` (compiled 2026-05-21) |
| **Platform** | macOS 15 (Darwin 25.5.0), ARM64, Apple M4 |
| **Python** | 3.12.13 |
| **Reporter** | Jon Addams (Customer Engineering) |
| **Date** | 2026-06-03 |
| **JIRA** | [NAPY-15](https://nutrient.atlassian.net/browse/NAPY-15) |

## Summary

`VisionFeatures.KEY_VALUE_REGION` is licensed on our key (the SDK banner lists "Vision: Key
Value Region") and the feature bitmask is accepted without error — but extraction output
contains **zero key/value-tagged elements** on documents full of key-value pairs (invoice
number, dates, totals, addresses). The returned elements are typed `paragraph`/`table`/`picture`
with roles like `Header`/`Text`/`Footer` — indistinguishable from a run without the feature.
From the caller's perspective the feature does nothing.

## Steps to reproduce

Verified live 2026-06-03 against a real scanned invoice, requesting ONLY the
KEY_VALUE_REGION feature:

```python
import os, json, collections
from nutrient_sdk import License, Document, Vision, VisionEngine, VisionFeatures
from nutrient_sdk.vlmprovider import VlmProvider
License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])

# input: rendered page of a scanned invoice (JPEG, per the NAPY-8 pre-render workaround)
with Document.open("ocr-invoice-page1.jpg") as doc:
    s = doc.get_settings()
    vs = s.get_vision_settings()
    vs.set_engine(VisionEngine.VLM_ENHANCED_ICR)
    vs.set_features(VisionFeatures.KEY_VALUE_REGION.value)   # ONLY this feature
    vs.set_provider(VlmProvider.CLAUDE)
    s.get_claude_api_settings().set_api_key(os.environ["ANTHROPIC_API_KEY"])
    raw = Vision.set(doc).extract_content()

elements = json.loads(raw).get("elements", [])
print("total:", len(elements))
print("types:", collections.Counter(str(e.get("type")) for e in elements))
print("roles:", collections.Counter(str(e.get("role")) for e in elements))
kv = [e for e in elements
      if "key" in (str(e.get("type","")) + str(e.get("role",""))).lower()
      or "value" in (str(e.get("type","")) + str(e.get("role",""))).lower()]
print("key/value-tagged:", len(kv))
```

## Expected behavior

With `KEY_VALUE_REGION` requested on an invoice, the output should contain elements tagged as
key/value regions (in `type`, `role`, or a dedicated field) pairing labels with values — e.g.
`("Invoice Number", "12345")`. At minimum, *something* in the output should differ from a run
without the feature.

## Actual behavior

```
total: 20
types: {'paragraph': 17, 'table': 2, 'picture': 1}
roles: {'Footer': 9, 'Text': 6, '': 3, 'Header': 1, 'SectionHeader': 1}
key/value-tagged: 0
```

The element schema (`bounds, confidence, id, pageNumber, readingOrder, role, text, type,
words`) contains no key/value field anywhere. No error, no warning — the feature flag is
silently ignored.

## Impact

- **A licensed entitlement produces nothing.** Customers paying for "Vision: Key Value Region"
  get no observable behavior from it.
- **The demo works around it:** `POST /api/extraction/fields` pairs the native feature with a
  schema-driven `Vision.describe()` prompt because only the latter actually returns key-value
  pairs (`app/services/extraction.py` `extract_fields()`). The Field Extraction frontend page
  shows an honest callout.
- Consistent with the pattern of other accepted-but-ignored Vision settings documented in
  `../2026-05-28-icr-engine-quality.md` (ICR confidence thresholds, `AiAugmenter.enable_*`
  flags — all no-ops).

## Workaround

Use `Vision.describe()` with a custom schema-driven prompt
(`vision_descriptor_settings.set_standard_prompt(...)`) to extract key-value pairs as JSON.
Works well, but it is a different API with no bounds/confidence per pair, and it shouldn't be
necessary when a dedicated feature exists.

## Root cause hypothesis

Either the KEY_VALUE_REGION model/stage isn't wired into the VLM extraction graph in this
build, or its output is produced but dropped before JSON serialization. The silent acceptance
of an undefined bitmask (SDK-027) suggests feature flags aren't validated against what the
pipeline actually executes.

## Reproduction artifacts

- `tests/fixtures/ocr-invoice.pdf` (pre-rendered to JPEG per the image-only-PDF workaround —
  see the [NAPY-8 report](./2026-06-01-vision-set-fails-on-image-only-pdfs.md))
- Workaround implementation: `app/services/extraction.py` `extract_fields()`
- No automated xfail test: it would require a live VLM call under `--forked`, which is
  fork-hostile (SDK-035). Documented-only in `../DEFECTS.md` (SDK-037).

## Suggested fix

Wire the KEY_VALUE_REGION feature into the extraction pipeline so requesting it yields tagged
key/value elements; or, if the feature is not implemented for this engine/provider
combination, raise `InvalidSettingsException` instead of silently accepting the flag.

## Related

- [NAPY-8 / SDK-026](./2026-06-01-vision-set-fails-on-image-only-pdfs.md) — the pre-render
  requirement this reproduction inherits.
- SDK-027 — undefined feature bitmasks silently accepted; same lack of feature-flag validation.
