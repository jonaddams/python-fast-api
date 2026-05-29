# ICR Engine Quality — Findings From 18 Real-World Handwriting Samples

**Author:** Jon Addams
**Date:** 2026-05-28
**SDK:** `nutrient-sdk==1.0.6`, `nutrient-sdk-native==1.0.6`
**Platform:** macOS 15 (ARM64, Apple M4), Python 3.12.13
**API:** `Vision.extract_content()` with `VisionEngine.ICR`, default settings

## Summary

We ran the ICR engine against 18 real-world handwriting samples spanning print-handwriting forms, cursive recipes, cursive letters, journal pages, and historical calligraphy. **The engine works well on one narrow case — clean print handwriting in structured forms — and degrades sharply on everything else.** On cursive narrative content the output is not transcription, it's barely-relevant noise.

A modern general-purpose vision-language model (Claude) transcribes the same cursive samples with near-perfect accuracy, suggesting ICR's model is not competitive with current VLM state-of-the-art for handwriting.

Recommend either (a) documenting ICR's intended scope explicitly so customers don't try to use it for cursive narrative, or (b) replacing the native ICR backend with a VLM-mediated pipeline for the handwriting-narrative use case.

## Test corpus

| Folder | Count | Style |
|---|---|---|
| `recipes/handwritten/` | 2 | Print handwriting (Reddit recipe + employment application) |
| `recipes/handwritten-cursive/` | 16 | Cursive (modern letters, recipes, journal page) + 1 historical calligraphy (Declaration of Independence) |

Source: image samples from Reddit's old-recipes subreddit and other public handwriting corpora. Not redistributable as a fixture set.

## Quantitative summary (ICR, default settings)

```
image                                                          time  elems words   conf chars
-----------------------------------------------------------------------------------------------
handwritten/handwritten-employment-application.jpg            11.8s    13    22   0.84   145
handwritten/se6kza6795yg1.jpeg                                 7.4s    29    79   0.59   324
handwritten-cursive/apricot-cake-recipe.jpg                    5.5s     5   113   0.64   495
handwritten-cursive/choc-pie-recipe.jpg                        6.5s     5    83   0.66   438
handwritten-cursive/dear-magnus-thank-you-note.jpg             1.4s     5   105   0.71   631
handwritten-cursive/dear-mark.png                             12.9s     5   313   0.69  1728
handwritten-cursive/dear-mr-frank.jpeg                         5.2s     3   112   0.72   540
handwritten-cursive/declaration.png                            1.9s     2    18   0.72    75
handwritten-cursive/don-baker-to-whom-it-may-concern.jpeg      9.8s    10    57   0.66   382
handwritten-cursive/fruit-cookies-recipe.jpg                   0.8s     4     7   0.70    22
handwritten-cursive/invoice.jpg                                6.4s    39    85   0.68   486
handwritten-cursive/journal-page.jpg                           7.0s     4   189   0.79  1152
handwritten-cursive/letter-to-lift-spirits.pdf                10.4s     7    98   0.76   464
handwritten-cursive/lt-john-delano-letter.jpg                 13.0s    10   129   0.52   655
handwritten-cursive/merry-xmas-cookies-recipe.jpg              7.7s     8    86   0.66   466
handwritten-cursive/oatmeal-cookies-recipe.jpg                 6.0s    14    81   0.51   316
handwritten-cursive/peanut-butter-cookies-recipe.jpg           3.7s     2    71   0.69   382
handwritten-cursive/us-declaration-of-independence.jpg        10.7s     6   187   0.70   783
```

Important caveat about confidence scores: **average confidence is not correlated with output quality.** The journal page scored 0.79 but produced gibberish. The Declaration of Independence scored 0.70 and is unreadable. ICR is confidently wrong on cursive.

## Qualitative findings by document type

### 🟢 Print handwriting in structured forms — production-quality

`handwritten-employment-application.jpg` extracted as:

```
Employment Application
Application information
Full Name:
Jane Doe
Phone Number:
Home Address:
Mailing Address:
4
555-O\OO
same as above
rev o st
```

Title, section headings, field labels, and the value "Jane Doe" all came through correctly. The phone number "555-OOOO" was misread (zeros as O) but recoverable. This is the use case where ICR delivers value.

### 🟡 Print handwriting on unstructured layout — mixed

`se6kza6795yg1.jpeg` (Reddit print-handwriting recipe) returned a mix of correct fragments ("Salt, pepper, Onion salt or dried chopped onions", "Sauce: Bake for", "Bake Abr. at 350°F") and unreadable noise. The print is legible to humans; ICR's spatial reasoning seems to get confused by the recipe-card layout rather than the script itself.

### 🔴 Cursive narrative content — unusable

`apricot-cake-recipe.jpg` returned:

> Coke & shied aprios) lain Ib with N € flous a 1,h à easposen (S.R 3 vab no powela laagpoon . canten ale 1 horela ind juica od 3 orange ) gan 3 anganing egas wash apricdi 9 alry a alon aus into veig smal pices [...]

A human (and Claude — see below) reads the same image as:

> Apricot Cake. Ing: 6 ozs. of dried apricots. ½ lb. of flour (S.R. or plain with ½ teaspoonful of baking powder). ½ teaspoonful carbonate of soda. Rind & juice of one orange. 6 ozs. sugar. 5 ozs. margarine. 2 eggs. Method. Wash apricots & dry in a cloth. Cut into very small pieces. [...]

ICR's output is not a noisy version of the truth — it's structurally different content, with mostly invented words. The recipe is unrecoverable from the ICR output even with aggressive post-processing.

The cursive letter `dear-magnus` follows the same pattern: structural words and the salutation/signature come through ("Dear Magnus", "Kind Regards, Erik Tronel & Sanita") but the body — which a human reads as "The International Business Law Team at Tilburg University wishes to express our gratitude for your recent guest lectures on Web 3.0 and the Metaverse" — is mangled to "The Business lean ot University Usishes G express OUR Gratitude fer OUR Recent or guest CURL lectures".

### 🔴 Historical calligraphy — unusable

The Declaration of Independence (cursive calligraphy on parchment) returned the masthead correctly — "In CONGRESS, July 4, 1776" (read as "Jury 4, 1776") — and then degraded. Body text is unrecoverable.

## Comparison against a general-purpose VLM (Claude)

For the same cursive apricot-cake recipe, Claude (via its vision capability) produced a complete, accurate transcription including ingredient quantities, units, and the full method paragraph. For the cursive Dear Magnus letter, Claude produced a near-perfect transcription including the institution name ("Tilburg University"), program name ("IBL-program"), and all three signatories.

This is one engineer with two images, not a systematic benchmark — but the gap is large enough that the conclusion is robust: **a modern general-purpose VLM is dramatically better than the current Nutrient ICR engine at cursive transcription.** The same is likely true of any current major VLM (OpenAI, Anthropic, Google) given how saturated this capability is.

## Tunables tested

`DocumentSettings` exposes nine settings groups that touch the ICR pipeline (`handwriting_settings`, `ocr_settings`, `segmenter_settings`, `reading_order_settings`, `deskew_settings`, `inference_layout_settings`, `words_detection_settings`, `ai_augmenter_settings`, `content_extraction_settings`). The most obvious levers for the quality issues observed above were swept on the test corpus. Findings:

**`HandwritingSettings.word_refining_method` — `HEURISTIC` (default) vs `VLM`.** Switching to `VLM` (with the Claude provider configured) produced byte-identical output to `HEURISTIC` on the `se6kza6795yg1.jpeg` print recipe — same 29 elements, same `fullText`. The VLM path *did* run (latency dropped from 15.5s to 7.2s, indicating a different code path), but the refining stage is downstream of segmentation and can't fix upstream misreads. Word-refining is not the lever for the quality issues we see.

**`SegmenterSettings.confidence_threshold` × `WordsDetectionSettings.confidence_threshold`.** Swept 9 combinations (0.5 / 0.7 / 0.85 each) on the `se6kza6795yg1.jpeg` recipe. **Every combination produced byte-identical output** — same 29 elements, same 0.59 avg confidence, same 324 chars, same phantom "x  1  ~" prefix from the decorative card elements. The documented confidence knobs are not gating the engine's final output. This is its own finding worth surfacing: a documented tunable that has no observable effect.

**`DeskewSettings`.** Tested on the tilted `dear-magnus-thank-you-note.jpg`:

| Config | Elements | Avg conf | Output character |
|---|---|---|---|
| Default (deskew on, tol=15°) | 5 | 0.71 | Coherent paragraph structure with mangled words |
| Deskew off | 6 | **0.81** | Higher confidence, but words from different parts of the letter scrambled into a single string |
| Tol=45° or 60° | 5 | 0.71 | Identical to default — 15° was already sufficient |

Deskew doesn't improve recognition accuracy at the word level — both versions have terrible word accuracy on cursive. What it does is recover **reading order**. With deskew off, you get a word salad where adjacent fragments physically belong on different lines. With it, you get paragraphs of incoherent text. Counterintuitively, deskew-off produced *higher* reported confidence (0.81 vs 0.71) — another data point that ICR confidence is not correlated with output quality.

**Net takeaway on tunables.** The recognition model itself is not configurable; only the surrounding pipeline. The configurable knobs we tested either had no effect (confidence thresholds) or moved the failure mode without improving accuracy (deskew, word-refining method). There is no combination of documented settings that closes the gap to a general-purpose VLM on the test samples.

## Notes on `Vision.describe()`

`Vision.describe()` with the Claude provider was tested and **does not transcribe**. It returns a meta-description of the document ("This is a handwritten recipe card on aged, cream-colored paper with visible staining and discoloration..."). For transcription via Claude, customers would need to either bypass the SDK and call the Anthropic API directly with a custom prompt, or the SDK would need to expose a `transcribe()`-style call (or a custom-prompt parameter on `describe()`).

## Recommendations

1. **Document ICR's intended scope explicitly.** The current API name and marketing suggest general handwriting recognition. The reality is the model performs well on print handwriting in structured forms and poorly on cursive narrative. Customers will get burned trying it for the latter.
2. **Add a `transcribe()` or prompt-customizable VLM path.** If a customer wants accurate transcription of cursive handwriting today, they cannot get it through the SDK — they have to leave the SDK entirely and use a third-party VLM API. The SDK could front-end Claude / OpenAI / Gemini with a transcription-specific prompt and offer it as `Vision.transcribe()` or similar.
3. **Consider retraining or replacing the ICR backend.** The current model appears to be confidently wrong on out-of-distribution inputs (high confidence + incorrect output is worse than low confidence + correct output, because customers will trust the confidence). If retraining is not feasible, routing cursive inputs through a hosted VLM may be the more pragmatic fix.
4. **Decouple confidence reporting from internal model certainty.** The 0.79 confidence on the gibberish-producing journal page suggests the score reflects the model's certainty about its own predictions, not the predictions' correctness. A calibrated confidence would let downstream code reject low-quality outputs.
5. **Investigate why the documented confidence thresholds appear to be no-ops on ICR.** `SegmenterSettings.confidence_threshold` and `WordsDetectionSettings.confidence_threshold` both default to 0.5 and accept values up to 1.0, but sweeping them through 0.5 / 0.7 / 0.85 on the print-recipe sample produced byte-identical output. Either the thresholds are wired into a different code path than ICR, or they're documented as configurable while the binary ignores them. Either way it surprises a customer who expects them to gate the output.

## Follow-up investigations (2026-05-29)

### `Vision.describe()` with a custom prompt

`DocumentSettings.get_vision_descriptor_settings()` exposes a `set_standard_prompt()` method (verified via introspection on 1.0.6). Setting a transcription-style prompt and calling `Vision.describe()` against the cursive `apricot-cake-recipe.jpg`:

**Default prompt result (first ~300 chars):**

> This is a handwritten recipe card on aged, yellowed paper with visible staining and wear. The title "Apricot Cake" appears at the top in cursive writing. The recipe is divided into two sections labeled "Ing:" (ingredients) and "Method:" on the left margin. The handwriting is in blue or black ink

**Custom transcription prompt result (first ~500 chars):**

> Apricot Cake.
>
> Ing: ½ pt. dried apricot (3.P. or
>      ½ lb. ½ lb. flour. 1 teasp. salt
>      ½ oz. baking powder.
>      1 tablespoon ful carbonate of soda.
>      ¼ pt. juice of one orange
>      ¼ pt. sugar.
>      ¼ pt. margarine.
>      2 eggs.
>
> Method: Soak apricots & chop fine
>         dim. Cut into very small
>         pieces.
>         Beat marg. + sugar to a
>         cream. Add eggs & apricots

**Verdict:** POSITIVE — custom prompts work; the SDK already provides a transcription path. The customer ergonomics gap is documentation, not capability: setting `get_vision_descriptor_settings().set_standard_prompt()` to a transcription-focused instruction causes `Vision.describe()` to return verbatim handwritten text rather than a visual meta-description.

## Demo decision

The companion `nutrient-sdk-samples` demo page for ICR (`/python-sdk/icr-extraction`) ships with the `handwritten-employment-application.jpg` sample as the default — the case where ICR demonstrably works. A short copy paragraph at the top sets expectations about the engine's narrow strength rather than promising general handwriting recognition.

## Raw outputs

All 18 ICR transcripts are at `recipes/icr-results/*.txt` in this repository's working tree (not committed — the source images are not redistributable). Comparison transcripts for the two Claude-spike images live in this document.
