# Claude vs. Nutrient ICR — Handwriting Transcription Comparison

**Date:** 2026-05-28
**Comparators:**
- Nutrient Python SDK `Vision` API, `VisionEngine.ICR`, `extract_content()`, default settings, `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6`.
- Anthropic Claude (Claude Opus 4.7) via the model's native vision capability, single-shot transcription with no prompt engineering.

**Purpose:** Document the gap between a general-purpose VLM and the Nutrient ICR engine on cursive handwriting, using two representative samples from a public Reddit corpus of old recipes and letters.

## Methodology

- Two images were chosen to represent contrasting cursive conditions: an aged recipe card (degraded paper, period handwriting, recipe layout) and a modern thank-you letter (clean paper, current cursive, narrative paragraphs).
- ICR was invoked through this project's `/api/extraction/icr` endpoint (`Vision.extract_content()` with `VisionEngine.ICR`, `VisionFeatures.ALL` minus the `FORM` bit). Output is the SDK's structured JSON; the `fullText` field is reproduced here verbatim.
- Claude received the raw image with the implicit instruction "transcribe this handwriting." Output is reproduced verbatim. Where the handwriting was ambiguous, the published transcription notes call it out.
- No post-processing was applied to either output. Neither engine was given any prior context about the document type, language, or expected content.

This is one engineer, two images — not a benchmark. The size of the gap is large enough that the qualitative conclusion is robust regardless of sample size.

## Files in this folder

| File | Purpose |
|---|---|
| `apricot-cake-recipe.jpg` | Source image #1 (cursive recipe on aged paper) |
| `apricot-cake-recipe.claude.md` | Claude transcription with reading notes |
| `apricot-cake-recipe.icr.txt` | ICR `fullText` output, verbatim |
| `dear-magnus-thank-you-note.jpg` | Source image #2 (modern cursive thank-you letter) |
| `dear-magnus-thank-you-note.claude.md` | Claude transcription with reading notes |
| `dear-magnus-thank-you-note.icr.txt` | ICR `fullText` output, verbatim |

## Sample 1 — Apricot Cake recipe (cursive on aged paper)

### Claude

> Apricot Cake.
>
> **Ing:** 6 ozs. of dried apricots. ½ lb. of flour (S.R. or plain with ½ teaspoonful of baking powder). ½ teaspoonful carbonate of soda. Rind & juice of one orange. 6 ozs. sugar. 5 ozs. margarine. 2 eggs.
>
> **Method.** Wash apricots & dry in a cloth. Cut into very small pieces. Mix marg. & sugar to a cream adding eggs. Mix all dry ingredients together including apricots & fold into the egg mixture. A little milk can be added if required. Mix mixture well before turning it into prepared tin. Put into moderate oven & cook 1½ hrs.

### ICR

> Coke & shied aprios) lain Ib with N € flous a 1,h à easposen (S.R 3 vab no powela laagpoon . canten ale 1 horela ind juica od 3 orange ) gan 3 anganing egas wash apricdi 9 alry a alon aus into veig smal pices Mix mangi A Lugan to 8 Cream mold a egas 2 - ald dhry inged - Yorghhe in a ad ng darie Ar a Pold into ha 299 alur te milh Can Se aadoled Ronached mix Ins xtuke we'e vejote lurning A wro prepared kin Put into hodenalis aven acor a - hrs.

### Observations

- Claude produced a usable, kitchen-ready transcription: every ingredient with quantity and unit, every method step, fractional measurements preserved.
- ICR's output is not a degraded version of the correct text — it is structurally different content. Most "words" are invented. The fragments that do match the original ("Cream", "egas" → eggs, "milh" → milk, "prepared kin" → prepared tin, "hrs") are scattered among gibberish and provide no reliable anchor for post-processing.
- ICR's reported confidence on this sample was **0.64** — moderate, not low. The score does not flag the output as unreliable.

## Sample 2 — "Dear Magnus" thank-you note (modern cursive letter)

### Claude

> NOTES
>
> Dear Magnus,
>
> The International Business Law Team at Tilburg University wishes to express our gratitude for your recent guest lectures on Web 3.0 and the Metaverse. Your insights were not only theoretically enriching but also immensely practical, offering our students a crucial perspective on these technologies.
>
> Your ability to blend theoretical knowledge with Real-World experience made the concepts accessible to our students. Your passion for the subject matter was evident throughout, igniting enthusiasm and curiosity among our audience. We deeply appreciate your dedication of time, expertise and invaluable contribution to the IBL-program. Your presence has enriched our academic community!
>
> Kind Regards, Erik, Tronel & Sanita

### ICR

> NOTES Dear Magnus, The Business lean ot University Usishes G express OUR Gratitude fer OUR Recent or guest CURL lectures (Web 3.0 adhd the Melaverse. OUURL Were Insights nob theoretic Only but oso immensely Offers RUA cal perspective on th, €echno les. practical, Youre &" blend ability theoretical Rrowledge Real- Udoeld experience made the concepts accessible Gur tO Stuclents. YOUR Passion foe the. Subject mates Was evident throughout . fe) enthousiasm and a Que Qudience We deeply appreci ded cakinn of lime , and inv on contri lbudtor. enRiched OW to the BL- program. Youk presence hos x + Kind Regards, Erik Tronel & Sanita x

### Observations

- Claude transcribed the letter end-to-end at near-publication accuracy: institution name ("Tilburg University"), program name ("IBL-program"), all three signatories preserved.
- ICR caught the salutation, "NOTES" header, signature line, and a scattering of common words ("blend", "theoretical", "knowledge", "Real-", "experience", "made the concepts accessible", "Kind Regards") but the body is otherwise unreadable. The institution name was missed entirely; the program identifier degraded to "BL- program."
- ICR's reported confidence on this sample was **0.71** — higher than the recipe, despite the body of the output being unusable for any downstream task.

## Aggregate findings

| Dimension | Claude | Nutrient ICR |
|---|---|---|
| **Recipe — recoverability** | Reader can bake from the transcript | Recipe cannot be reconstructed |
| **Letter — recoverability** | Letter can be quoted or summarized | Salutation and signature recoverable; body is noise |
| **Proper nouns** | "Tilburg University", "IBL-program" preserved | Missed |
| **Numeric quantities and units** | "6 ozs.", "½ lb.", "1½ hrs" preserved | Mangled or absent |
| **Reported confidence vs. truth** | n/a (no confidence score) | 0.64 / 0.71 on outputs that are essentially wrong |
| **Latency (single image, this hardware)** | n/a (in-model) | 5.5s / 1.4s for ICR |

## Practical implications

1. **For cursive handwriting transcription today, a general-purpose VLM dominates Nutrient ICR.** Customers with this workload should not be steered to ICR.
2. **ICR's reported confidence does not signal output quality.** Building downstream logic that thresholds on ICR confidence (e.g., "auto-accept if conf > 0.7") will silently approve unusable content on cursive inputs.
3. **The gap is not closeable with prompt engineering or post-processing on the ICR side.** The output is not a noisy version of the truth that could be cleaned up — it is largely invented content. Any "fix" would need to happen at the model layer (retraining, swapping the backend, or routing cursive inputs through a VLM).
4. **The SDK could close this gap by adding a `Vision.transcribe()`-style call that uses a configured VLM provider.** The Anthropic / OpenAI / Gemini APIs are already exposed by the SDK for `describe()`; reusing that plumbing with a transcription prompt would give customers a high-quality path through the SDK rather than around it.

## Caveats

- Single engineer, two images. Treat the conclusions as directional, not statistically rigorous.
- Claude's transcription was performed without an explicit "be conservative / mark uncertainty" prompt. With such prompting, lower-confidence sections would be flagged rather than asserted.
- This comparison did not test the case where ICR is strong: clean print handwriting in known form layouts. See the companion document at `docs/sdk-feedback/2026-05-28-icr-engine-quality.md` for that side of the picture.
