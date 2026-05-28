# Form Field Detection Quality — Findings from Real-World Government PDFs

**Author:** Jon Addams
**Date:** 2026-05-28
**SDK:** `nutrient-sdk==1.0.6`, `nutrient-sdk-native==1.0.6`
**Platform:** macOS 15 (ARM64, Apple M4), Python 3.12.13
**API:** `PdfEditor.detect_and_add_form_fields()` configured via `DocumentSettings.get_form_recognition_settings()`

## Summary

While preparing a public demo of the new `detect_and_add_form_fields()` API, we tested the detector against 10 real-world unfielded government forms (IRS, US State Dept, OPM, USCIS). The detector is functional but produces inconsistent results across documents:

- **Severe over-detection** on layout-heavy forms (W-4 returned 180 fields where ~15 exist).
- **Severe under-detection** on others (I-9 returned 4 fields where 30+ exist).
- **Inconsistent class detection** — checkboxes detected on some forms, missed on others with similar layouts.
- **Misses prominent fields** like applicant-name fields at the top of standard tax forms (1040EZ).
- **Generic typing** — every detected field returns as the base `PdfFormField` rather than a specific subclass (`PdfTextField`, `PdfCheckBoxField`, etc.), even when shape would clearly indicate checkbox vs. text region.

Adjusting `confidence_threshold` only trades one failure mode for another — there's no single threshold that produces reasonable results across the test set.

## Test set

| File | Form | Pages | Size (KB) | Approx. real field count |
|---|---|---|---|---|
| `ds11-flat.pdf` | DS-11 US Passport Application | 6 | 1175 | ~30 |
| `ds64-flat.pdf` | DS-64 Lost/Stolen Passport | 2 | 489 | ~15-20 |
| `ds82-flat.pdf` | DS-82 Passport Renewal | 6 | 1735 | ~25-30 |
| `f1040ez--2016-flat.pdf` | IRS 1040EZ (2016) | 2 | 103 | ~12-15 |
| `f940-flat.pdf` | IRS 940 Federal Unemployment | 3 | 802 | ~30-40 |
| `fct1x-flat.pdf` | IRS CT-1X | 6 | 267 | ~30-50 |
| `fw4-flat.pdf` | IRS W-4 | 5 | 111 | ~15-20 |
| `i-9-flat.pdf` | USCIS I-9 | 4 | 655 | ~30+ |
| `sf3104-flat.pdf` | SF-3104 FERS Beneficiary | 8 | 615 | ~50 |
| `sf_2800-flat.pdf` | SF-2800 CSRS Death Benefits | 7 | 776 | ~80 |

## Detection counts vs. confidence threshold

The default threshold is **0.35** per `FormRecognitionSettings.get_confidence_threshold()`.

| File | 0.35 (default) | 0.50 | 0.70 | 0.75 | 0.85 | 0.95 |
|---|---:|---:|---:|---:|---:|---:|
| ds11-flat.pdf | — | — | — | 89 | — | — |
| ds64-flat.pdf | — | — | — | 10 | — | — |
| ds82-flat.pdf | — | — | — | 75 | — | — |
| f1040ez--2016-flat.pdf | — | — | — | 9 | — | — |
| f940-flat.pdf | — | — | — | 53 | — | — |
| fct1x-flat.pdf | — | — | — | 160 | — | — |
| fw4-flat.pdf | — | — | — | 180 | — | — |
| i-9-flat.pdf | — | — | — | 4 | — | — |
| sf3104-flat.pdf | **245** | 178 | 124 | 94 | 36 | 1 |
| sf_2800-flat.pdf | **230** | 171 | 101 | 81 | 55 | 9 |

The SF-3104 sweep (245 → 178 → 124 → 94 → 36 → 1) shows the threshold acts as a steep precision/recall slider. The 0.85 → 0.95 cliff (36 → 1 on SF-3104, 55 → 9 on SF-2800) suggests genuinely high-confidence detections cluster in the 0.70–0.85 band — but there's no threshold that produces good results across the test set.

## Specific failure modes observed

### 1. False negatives on prominent fields

**1040EZ at threshold 0.75 (9 fields detected, ~12-15 real):**

The detector misses the applicant-name and SSN fields that occupy the top quarter of page 1 — the most prominent and visually obvious fillable regions on the form. These are large, well-isolated text-entry rectangles with explicit underlines. They should be detection layups.

**I-9 at threshold 0.75 (4 fields detected, 30+ real):**

The USCIS I-9 has dozens of standardized text and date fields organized in clean sections. Returning 4 fields is effectively a non-detection — the form looks unmodified after the call.

### 2. False positives on decorative boxes

**SF-2800 and SF-3104 at the default 0.35:** The detector adds form fields over decorative rectangles, section dividers, and table cell borders that are not fillable regions. Result: 245 fields on a form with ~50 real ones.

**W-4 at threshold 0.75: 180 detections** — the form has ~15-20 real fields. The detector appears to be triggering on every cell of the deduction-worksheet tables and the multi-column structure on page 3.

### 3. Inconsistent class detection

Comparing 1040EZ (catches checkbox fields) against DS-64 and W-4 (misses checkboxes on similar-looking layouts), it appears the detector classifies checkboxes inconsistently across documents. From a customer perspective, the same visual shape (square check box with label) is sometimes detected and sometimes ignored, with no obvious pattern based on size, position, or surrounding text.

### 4. Generic typing on every detection

Every detected field returns as a generic `PdfFormField` instance (verified via `type(field).__name__`). Specific subclasses like `PdfTextField`, `PdfCheckBoxField`, `PdfRadioButtonField`, etc. exist in the SDK and are returned correctly by other operations (e.g. when reading fields that were natively part of a PDF), but the detector never produces them. This means a calling application can't render typed inputs (text vs. checkbox vs. radio) based on the detection output alone — additional inspection of widget geometry would be required, defeating much of the value of "detect AND add form fields."

## Suggested improvements

1. **Per-field confidence in the output.** Even if the detector remains imperfect, exposing each detection's confidence score (rather than only allowing a single global threshold) would let calling code post-filter or rank results.
2. **Field subtype classification.** Return `PdfTextField`/`PdfCheckBoxField`/etc. when the detector has high confidence on shape, falling back to `PdfFormField` only when ambiguous.
3. **Targeted model retraining on real-world tax/government forms.** The detector seems tuned on layouts closer to the Nutrient SDK guide's `input_forms_detection.pdf` sample (clean, isolated regions, modest field counts). Real-world IRS / USCIS / State Dept forms have dense tabular layouts and explicit section borders that produce false positives, and dense same-column field stacks that produce false negatives.
4. **Better documentation of the threshold semantics.** The default `0.35` is permissive enough that it nearly always over-detects on dense forms. Either raise the default toward 0.7, or document the threshold's behavior with an empirical curve for representative documents.

## Reproduction

The 10 input PDFs are at the project root of `/Users/jonaddamsnutrient/SE/code/python-fast-api/` and on the customer's local machine — not redistributable as a public dataset since they are official government form templates. All forms are downloadable directly from the originating agency (IRS, OPM, USCIS, US State Dept).

To reproduce one example:

```python
from nutrient_sdk import License, Document, PdfEditor, SdkSettings
License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])
SdkSettings.get_form_recognition_settings().set_confidence_threshold(0.75)

with Document.open("fw4-flat.pdf") as doc:
    editor = PdfEditor.edit(doc)
    editor.detect_and_add_form_fields()
    print(editor.get_form_field_collection().get_count())  # → 180 on a ~15-field form
```

## Demo decision

Given the inconsistent quality, the public demo at `app/python-sdk/form-detection/page.tsx` in `nutrient-sdk-samples` ships with:
- **F940 at threshold 0.75** as the default sample — best signal-to-noise among the tested forms.
- A confidence slider so users can see the precision/recall tradeoff directly rather than discovering the limitation by surprise.
- Honest framing in copy — the feature is positioned as a starting point that customers can refine, not a finished detector.
