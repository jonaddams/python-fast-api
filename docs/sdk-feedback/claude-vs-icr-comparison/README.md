# Claude vs. Nutrient ICR — Handwriting Transcription Comparison

**Date:** 2026-05-28
**Comparators:**
- Nutrient Python SDK `Vision` API, `VisionEngine.ICR`, `extract_content()`, default settings, `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6`.
- Anthropic Claude (Claude Opus 4.7) via the model's native vision capability, single-shot transcription with no prompt engineering.

**Purpose:** Document the gap between a general-purpose VLM and the Nutrient ICR engine on handwriting, using three representative samples drawn from a public Reddit corpus of old recipes and letters.

## Methodology

- Three images were chosen to span the handwriting difficulty range: a clean print-handwriting recipe card with structured fields (the case where ICR should perform best), an aged cursive recipe card (period handwriting on degraded paper), and a modern cursive thank-you letter (current handwriting on clean paper).
- ICR was invoked through this project's `/api/extraction/icr` endpoint (`Vision.extract_content()` with `VisionEngine.ICR`, `VisionFeatures.ALL` minus the `FORM` bit). Output is the SDK's structured JSON; the `fullText` field is reproduced here verbatim.
- Claude received the raw image with the implicit instruction "transcribe this handwriting." Output is reproduced verbatim. Where the handwriting was ambiguous, the published transcription notes call it out.
- No post-processing was applied to either output. Neither engine was given any prior context about the document type, language, or expected content.

This is one engineer, two images — not a benchmark. The size of the gap is large enough that the qualitative conclusion is robust regardless of sample size.

## Files in this folder

| File | Purpose |
|---|---|
| `heavenly-hamburgers-recipe.jpeg` | Source image #1 (print-handwriting recipe card, structured) |
| `heavenly-hamburgers-recipe.claude.md` | Claude transcription with reading notes |
| `heavenly-hamburgers-recipe.icr.txt` | ICR `fullText` output, verbatim |
| `apricot-cake-recipe.jpg` | Source image #2 (cursive recipe on aged paper) |
| `apricot-cake-recipe.claude.md` | Claude transcription with reading notes |
| `apricot-cake-recipe.icr.txt` | ICR `fullText` output, verbatim |
| `dear-magnus-thank-you-note.jpg` | Source image #3 (modern cursive thank-you letter) |
| `dear-magnus-thank-you-note.claude.md` | Claude transcription with reading notes |
| `dear-magnus-thank-you-note.icr.txt` | ICR `fullText` output, verbatim |

## Sample 1 — "Heavenly Hamburgers" recipe (print handwriting, structured card)

This is the case ICR is supposed to be good at: clean, block-style print handwriting on a well-structured recipe card with clear field boundaries.

### Claude

> **Heavenly Hamburgers**
>
> *Recipe from the kitchen of:* Originally from Aunt Lola
>
> - 2 lbs. ground beef
> - 3/4 C. oatmeal
> - 3/4 C. canned (evaporated) milk
> - Salt, pepper, onion salt (or dried chopped onions)
>
> Make into thick patties (10 to 12) and brown. Put in baking dish. Cover with sauce. Bake 1 hr. at 350° F
>
> **Sauce:** 1 C. Catsup · 2 Tbsp. Worchestershire sauce · 2 Tbsp. Vinegar · 2 Tbsp. Sugar · 1 ½ C. water
>
> *from Lola to Grandmommy to Mom to Ruth*
>
> Bake at 350° F for 1 hour

### ICR

> x  1  ~  2 lbs a  Or - nally  orat milk  Salt, pepper, Onion satt er dried chonged onions )  Make ints thick pathes Putin ba KingA ish "Sauce. Bake Abr. at 350 F  2 Sauce  | A C.  a Ths v  wd Th $ neg ar. Sugar  from lela to  _te  Bake for  -  -  Sauce:  _____  ow wren - > ven wns Whal'' Ton Cao what  ¥ 2 Fm F  Reeipe from the kituhgn of:  oe  A

### Observations

- Even on what should be ICR's strongest case — clear print handwriting in structured fields — Claude transcribes the recipe end-to-end while ICR returns fragmentary, mostly unusable text. A cook cannot make these hamburgers from the ICR output.
- ICR did catch some structural anchors: "Salt, pepper, Onion satt (saIt) er dried chonged (chopped) onions", "Make ints (into) thick pathes (patties)", "Bake Abr. (1hr.) at 350 F", "Sauce:", "from lela to", "Bake for", "Recipe from the kituhgn (kitchen) of:". The skeleton is recognizable.
- But the structured fields ICR is supposed to handle — quantities, units, ingredient names — are mangled or absent. The ingredient list is not extractable. The sauce sub-recipe is not extractable. Only the section labels survive.
- ICR appears to have been confused by the decorative pre-printed elements (the cheese illustration, the "Here's what's cookin':" red text, the lined rules on the card). The phantom "x  1  ~" at the top of the output and the misread "Reeipe from the kituhgn of:" at the end likely come from the decorative graphics rather than the handwriting itself.
- This sample shows the upper-bound limit of the current ICR engine on real-world print handwriting: in a controlled form context with hand-printed values in pre-defined boxes, it works (per the employment-application case in the companion `2026-05-28-icr-engine-quality.md`); on a less structured but still print and well-organized recipe card, it produces output unfit for downstream use.

## Sample 2 — Apricot Cake recipe (cursive on aged paper)

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

## Sample 3 — "Dear Magnus" thank-you note (modern cursive letter)

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
| **Print recipe (Heavenly Hamburgers) — recoverability** | Reader can cook from the transcript | Section labels survive; ingredients, quantities, sauce list unrecoverable |
| **Cursive recipe (apricot) — recoverability** | Reader can bake from the transcript | Recipe cannot be reconstructed |
| **Cursive letter (Dear Magnus) — recoverability** | Letter can be quoted or summarized | Salutation and signature recoverable; body is noise |
| **Proper nouns** | "Tilburg University", "IBL-program", "Aunt Lola", "Worchestershire" preserved | Mostly missed; "lela" for Lola, "Worchestershire" mangled |
| **Numeric quantities and units** | "2 lbs.", "3/4 C.", "1 hr.", "350° F", "½ lb.", "1½ hrs" preserved | Mangled or absent across all three samples |
| **Decorative card elements** | Recognized as decoration; ignored | Confused for text; produces phantom output ("x  1  ~", "Reeipe from the kituhgn of:") |
| **Reported confidence vs. truth** | n/a (no confidence score) | 0.59 / 0.64 / 0.71 — uncorrelated with actual quality |
| **Latency (single image, this hardware)** | n/a (in-model) | 7.4s / 5.5s / 1.4s for ICR |

## Practical implications

1. **For real-world handwriting transcription today — print *or* cursive — a general-purpose VLM dominates Nutrient ICR.** Customers with this workload should not be steered to ICR. The print-handwriting case was expected to be ICR's strength; the structured recipe card shows that "expected strength" still produces output that's not extractable for downstream use.
2. **ICR's reported confidence does not signal output quality.** Confidence ranged from 0.59 to 0.71 across the three samples, with no correlation to whether the output was usable. Building downstream logic that thresholds on ICR confidence (e.g., "auto-accept if conf > 0.7") will silently approve unusable content.
3. **The gap is not closeable with prompt engineering or post-processing on the ICR side.** The output is not a noisy version of the truth that could be cleaned up — it is largely invented content. Any "fix" would need to happen at the model layer (retraining, swapping the backend, or routing inputs through a VLM).
4. **ICR's clean-success window is narrower than the API name suggests.** The companion engine-quality doc shows ICR working well on a clean print employment-application form (`handwritten-employment-application.jpg`). The "Heavenly Hamburgers" card here is also print handwriting on a structured layout — yet ICR fails on it because the card has decorative graphics, lined rules, and free-form positioning that the model gets confused by. The boundary between "ICR works" and "ICR doesn't" is not "print vs. cursive" but something closer to "rigid form field vs. anything else."
5. **The SDK could close this gap by adding a `Vision.transcribe()`-style call that uses a configured VLM provider.** The Anthropic / OpenAI / Gemini APIs are already exposed by the SDK for `describe()`; reusing that plumbing with a transcription prompt would give customers a high-quality path through the SDK rather than around it.

## Caveats

- Single engineer, three images. Treat the conclusions as directional, not statistically rigorous.
- Claude's transcription was performed without an explicit "be conservative / mark uncertainty" prompt. With such prompting, lower-confidence sections would be flagged rather than asserted.
- This comparison did not test the case where ICR is strong: clean print handwriting in known form layouts. See the companion document at `docs/sdk-feedback/2026-05-28-icr-engine-quality.md` for that side of the picture.
