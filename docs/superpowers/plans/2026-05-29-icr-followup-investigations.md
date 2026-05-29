# ICR Follow-up Investigations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the seven untested investigations identified during the ICR/handwriting feedback work — `Vision.describe()` custom prompt, OpenAI provider parity, custom-VLM endpoint, multi-language ICR, AiAugmenter toggles, form-detection on a fielded PDF, and the `_vision_keep_alive` workaround on 1.0.6. Output findings into the existing SDK feedback docs and apply targeted code changes only where findings warrant.

**Architecture:** Most tasks are bounded investigations (run code, capture output, document). Each task appends a section to `docs/sdk-feedback/2026-05-28-icr-engine-quality.md` under a new "Follow-up investigations (2026-05-29)" subsection. Two tasks (#1 if it works, #7 if clean) can produce permanent code changes — those get their own commits and tests.

**Tech Stack:** Python 3.12, FastAPI, `nutrient-sdk==1.0.6`, pytest, the existing `.venv` and `Makefile`.

**Spec/context:** [`docs/sdk-feedback/2026-05-28-icr-engine-quality.md`](../sdk-feedback/2026-05-28-icr-engine-quality.md) and [`docs/sdk-feedback/claude-vs-icr-comparison/`](../sdk-feedback/claude-vs-icr-comparison/) are the existing artifacts being extended.

---

## Background for the implementing engineer

The Nutrient Python SDK (1.0.6) exposes a `Vision` API with `OCR`, `ICR`, and `VLM_ENHANCED_ICR` engines plus a `describe()` call that routes through a configurable VLM provider (Claude or OpenAI). A prior comparison showed Nutrient's ICR is dramatically outperformed by a general-purpose VLM on handwriting. These seven investigations close known gaps in that comparison.

Working directory: `/Users/jonaddamsnutrient/SE/code/python-fast-api`.
Branch base: `main`.

Useful pre-existing helpers in the repo:
- `Makefile` — `make test`, `make dev`, `make install`
- `app/services/extraction.py` — wraps `Vision.extract_content()` with `VisionEngine.{ADAPTIVE_OCR, ICR, VLM_ENHANCED_ICR}` and exposes a `_vision_keep_alive` workaround list (`extraction.py:9`)
- `app/services/forms.py` — wraps `PdfEditor.detect_and_add_form_fields()` with optional confidence override
- `tests/fixtures/input_forms_detection.pdf`, `tests/fixtures/account-registration-form.pdf`, `tests/fixtures/input_ocr_multiple_languages.png`
- Sample images at `recipes/handwritten/*` and `recipes/handwritten-cursive/*` (untracked but present in the working tree)

The license now includes `vision_form`. `.env` has `NUTRIENT_LICENSE_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `docs/sdk-feedback/2026-05-28-icr-engine-quality.md` | Append | New "Follow-up investigations (2026-05-29)" section, one subsection per task |
| `docs/sdk-feedback/claude-vs-icr-comparison/README.md` | Optional append (Task 1 only) | Update if `describe()` custom prompt closes the gap |
| `docs/sdk-feedback/claude-vs-icr-comparison/index.html` | Optional append (Task 1 only) | Same |
| `app/services/extraction.py` | Modify (Task 1 if positive, Task 7 if positive) | Add `describe_image()` helper / remove `_vision_keep_alive` |
| `app/routers/extraction.py` | Modify (Task 1 if positive) | Add `POST /api/extraction/describe` endpoint |
| `tests/test_extraction.py` | Modify (Tasks 1, 4, 7) | New tests if code changes warrant |

---

## Branch + commit strategy

One branch, multiple commits. Most tasks add a markdown subsection plus a small bash log; only Tasks 1 and 7 *might* introduce code. Branch off main:

```bash
git checkout main && git pull
git checkout -b icr-followup-investigations
```

After all tasks complete, open one PR. Do not squash so each task's commit is reviewable independently.

---

## Task 1: `Vision.describe()` with a custom prompt

**Hypothesis:** `Vision` exposes a `vision_descriptor_settings` group with a `standard_prompt` field. Setting it to a transcription-style prompt may make `describe()` return verbatim text instead of a meta-description.

**Files:**
- Read: SDK module surface (Python introspection only — no file edits in this task's first half)
- Modify (conditional): `app/services/extraction.py`, `app/routers/extraction.py`, `tests/test_extraction.py`
- Modify: `docs/sdk-feedback/2026-05-28-icr-engine-quality.md`

- [ ] **Step 1: Confirm the prompt knob exists**

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
.venv/bin/python -c "
import os
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
with Document.open('tests/fixtures/input_ocr_multiple_languages.png') as d:
    vds = d.get_settings().get_vision_descriptor_settings()
    print('VisionDescriptorSettings setters:')
    for m in sorted(dir(vds)):
        if m.startswith('set_'):
            getter = getattr(vds, m.replace('set_', 'get_'), None)
            try:
                cur = getter() if getter else '?'
            except Exception as e:
                cur = f'<error: {e}>'
            print(f'  {m}() — current: {cur!r}')
" 2>&1 | grep -v "Nutrient Licensing\|This is a demo\|compiled at\|Features:\|Copyright\|Welcome\|This version\|bundle identifier\|Guides &\|Already a\|^│\|^└\|^┌\|^$"
```

Expected: a list of setters including `set_standard_prompt`, `set_level`. Note the current default `standard_prompt` value.

- [ ] **Step 2: Run baseline `describe()` against a cursive recipe**

```bash
.venv/bin/python << 'PYEOF' > /tmp/task1-baseline.txt 2>&1
import os
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, Vision
from nutrient_sdk.vlmprovider import VlmProvider
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
IMG = 'recipes/handwritten-cursive/handwritten-cursive-apricot-cake-recipe.jpg'
with Document.open(IMG) as d:
    s = d.get_settings()
    s.get_vision_settings().set_provider(VlmProvider.CLAUDE)
    s.get_claude_api_settings().set_api_key(os.environ['ANTHROPIC_API_KEY'])
    out = Vision.set(d).describe()
print(out)
PYEOF
head -c 600 /tmp/task1-baseline.txt
```

Expected: meta-description ("This is a handwritten recipe card on aged paper…"), as previously observed.

- [ ] **Step 3: Run with a transcription prompt**

```bash
.venv/bin/python << 'PYEOF' > /tmp/task1-transcribe.txt 2>&1
import os
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, Vision
from nutrient_sdk.vlmprovider import VlmProvider
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
IMG = 'recipes/handwritten-cursive/handwritten-cursive-apricot-cake-recipe.jpg'
PROMPT = "Transcribe all handwritten text in this image verbatim. Preserve line breaks. Do not describe the image; only return the transcribed text. If a word is unreadable, write [illegible] in its place."
with Document.open(IMG) as d:
    s = d.get_settings()
    s.get_vision_descriptor_settings().set_standard_prompt(PROMPT)
    s.get_vision_settings().set_provider(VlmProvider.CLAUDE)
    s.get_claude_api_settings().set_api_key(os.environ['ANTHROPIC_API_KEY'])
    out = Vision.set(d).describe()
print(out)
PYEOF
cat /tmp/task1-transcribe.txt
```

Expected: one of two outcomes —
- **Positive:** Returns a transcription matching what Claude produced directly in the comparison (recipe text with "Apricot Cake", ingredient quantities, method steps).
- **Negative:** Still returns a meta-description ignoring the custom prompt, or fails with a `VisionError`.

- [ ] **Step 4: Document the finding** in `docs/sdk-feedback/2026-05-28-icr-engine-quality.md`

Append a new top-level section near the end of the file, before "## Demo decision":

```markdown
## Follow-up investigations (2026-05-29)

### `Vision.describe()` with a custom prompt

`DocumentSettings.get_vision_descriptor_settings()` exposes a `set_standard_prompt()` method. Setting a transcription-style prompt and calling `Vision.describe()` against the cursive apricot-cake recipe:

**Default prompt result:** [paste first 200 chars of /tmp/task1-baseline.txt]

**Custom transcription prompt result:** [paste first 400 chars of /tmp/task1-transcribe.txt]

**Verdict:** [POSITIVE — custom prompts work; the SDK already provides a transcription path | NEGATIVE — custom prompt is ignored / fails; the SDK does not provide a transcription path]

If POSITIVE: this changes the headline finding. The SDK *does* expose a high-quality handwriting transcription path; it just isn't documented as such. The customer ergonomics gap is documentation, not capability.

If NEGATIVE: the original feedback stands — recommend exposing a `transcribe()` call or a prompt parameter on `describe()`.
```

Fill in `[paste ...]` and pick the right `[VERDICT]` branch based on Step 3's output.

- [ ] **Step 5: If POSITIVE, add a backend endpoint**

If Step 3 returned a transcription, add `/api/extraction/describe` to the FastAPI app so the demo frontend can use it.

In `app/services/extraction.py`, add a new function after `extract_text_vlm`:

```python
def describe_image(
    image_bytes: bytes,
    original_filename: str,
    *,
    prompt: str | None = None,
    provider: str = "claude",
) -> dict:
    """Run Vision.describe() with an optional custom prompt."""
    with tempfile.NamedTemporaryFile(suffix="-" + original_filename, delete=False) as inp:
        inp.write(image_bytes)
        inp_path = inp.name

    try:
        with Document.open(inp_path) as doc:
            s = doc.get_settings()
            if prompt:
                s.get_vision_descriptor_settings().set_standard_prompt(prompt)
            if provider.lower() == "claude":
                from nutrient_sdk.vlmprovider import VlmProvider
                s.get_vision_settings().set_provider(VlmProvider.CLAUDE)
                s.get_claude_api_settings().set_api_key(os.environ["ANTHROPIC_API_KEY"])
            elif provider.lower() == "openai":
                from nutrient_sdk.vlmprovider import VlmProvider
                s.get_vision_settings().set_provider(VlmProvider.OPENAI)
                s.get_open_ai_api_endpoint_settings().set_api_key(os.environ["OPENAI_API_KEY"])
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            vision = Vision.set(doc)
            _vision_keep_alive.append(vision)
            text = vision.describe()

        return {
            "engine": "VLM_DESCRIBE",
            "filename": original_filename,
            "provider": provider,
            "promptUsed": prompt or "(default)",
            "text": text,
        }
    finally:
        os.unlink(inp_path)
```

In `app/routers/extraction.py`, add:

```python
from pydantic import BaseModel
from app.services.extraction import (
    extract_text_ocr,
    extract_text_icr,
    extract_text_vlm,
    describe_image,
    LocalVlmUnavailable,
)


class DescribeRequest(BaseModel):
    prompt: str | None = None
    provider: str = "claude"


@router.post("/describe")
async def describe(file: UploadFile = File(...), prompt: str | None = Form(None), provider: str = Form("claude")):
    try:
        data = await file.read()
        return describe_image(data, file.filename or "input", prompt=prompt, provider=provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

(The existing router file already imports `extract_text_ocr` etc.; modify the import line to include `describe_image` per the snippet above. The current router uses `from fastapi import APIRouter, UploadFile, File, HTTPException` — add `Form`.)

In `tests/test_extraction.py`, append:

```python
def test_describe_endpoint_returns_text(client: TestClient, sample_image_bytes: bytes, sample_image_name: str):
    response = client.post(
        "/api/extraction/describe",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
        data={"provider": "claude"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_DESCRIBE"
    assert body["provider"] == "claude"
    assert isinstance(body["text"], str) and len(body["text"]) > 0
```

- [ ] **Step 6: Run the test (if Step 5 ran)**

```bash
make test
```

Expected: previously-passing count + 1 new test, all passing.

- [ ] **Step 7: Commit**

If only docs changed:

```bash
git add docs/sdk-feedback/2026-05-28-icr-engine-quality.md
git commit -m "docs(icr): document Vision.describe() custom-prompt investigation"
```

If code also changed:

```bash
git add app/services/extraction.py app/routers/extraction.py tests/test_extraction.py docs/sdk-feedback/2026-05-28-icr-engine-quality.md
git commit -m "feat(extraction): add /api/extraction/describe with custom prompt support

Investigation showed Vision.describe() honors set_standard_prompt() and
returns verbatim transcriptions when prompted appropriately. Exposing
this via a new endpoint gives customers a high-quality handwriting
transcription path that stays inside the SDK."
```

---

## Task 2: OpenAI VLM provider parity

**Hypothesis:** All VLM tests so far used Claude. The SDK also supports `VlmProvider.OPENAI`. Behavior may or may not match.

**Files:**
- Modify: `docs/sdk-feedback/2026-05-28-icr-engine-quality.md`

- [ ] **Step 1: Run `describe()` with OpenAI provider**

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
.venv/bin/python << 'PYEOF' > /tmp/task2-openai.txt 2>&1
import os
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, Vision
from nutrient_sdk.vlmprovider import VlmProvider
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
IMG = 'recipes/handwritten-cursive/handwritten-cursive-apricot-cake-recipe.jpg'
with Document.open(IMG) as d:
    s = d.get_settings()
    s.get_vision_settings().set_provider(VlmProvider.OPENAI)
    s.get_open_ai_api_endpoint_settings().set_api_key(os.environ['OPENAI_API_KEY'])
    out = Vision.set(d).describe()
print(out)
PYEOF
cat /tmp/task2-openai.txt
```

Expected: a description or transcription (depending on Task 1's outcome). If it fails, the error message is the finding.

- [ ] **Step 2: If Task 1 was positive, also test custom-prompt transcription via OpenAI**

```bash
.venv/bin/python << 'PYEOF' > /tmp/task2-openai-transcribe.txt 2>&1
import os
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, Vision
from nutrient_sdk.vlmprovider import VlmProvider
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
IMG = 'recipes/handwritten-cursive/handwritten-cursive-apricot-cake-recipe.jpg'
PROMPT = "Transcribe all handwritten text in this image verbatim. Preserve line breaks. Do not describe the image; only return the transcribed text."
with Document.open(IMG) as d:
    s = d.get_settings()
    s.get_vision_descriptor_settings().set_standard_prompt(PROMPT)
    s.get_vision_settings().set_provider(VlmProvider.OPENAI)
    s.get_open_ai_api_endpoint_settings().set_api_key(os.environ['OPENAI_API_KEY'])
    out = Vision.set(d).describe()
print(out)
PYEOF
cat /tmp/task2-openai-transcribe.txt
```

If Task 1 was NEGATIVE: skip this step.

- [ ] **Step 3: Document parity finding**

Append under the "Follow-up investigations (2026-05-29)" section:

```markdown
### OpenAI VLM provider parity

Tested the same cursive apricot-cake recipe through `VlmProvider.OPENAI` with the API key from `.env`:

**Default describe() prompt:** [paste 300 chars from /tmp/task2-openai.txt]

[If Task 1 positive:]
**Custom transcription prompt:** [paste 400 chars from /tmp/task2-openai-transcribe.txt]

**Verdict:** [OpenAI behaves identically to Claude — same describe-vs-transcribe behavior, same approximate quality | OpenAI behaves differently: <describe>]

This confirms / contradicts that the `describe()` behavior is provider-agnostic. [Add one sentence on what this means: if both providers respect custom prompts, the SDK has a viable transcription path; if only one does, document which]
```

- [ ] **Step 4: Commit**

```bash
git add docs/sdk-feedback/2026-05-28-icr-engine-quality.md
git commit -m "docs(icr): document OpenAI VLM provider parity investigation"
```

---

## Task 3: `CustomVlmApiSettings`

**Hypothesis:** `DocumentSettings.get_custom_vlm_api_settings()` exists, suggesting customers can plug in their own OpenAI-compatible VLM endpoint (e.g., LM Studio, Ollama, vLLM, a self-hosted Llama).

**Files:**
- Modify: `docs/sdk-feedback/2026-05-28-icr-engine-quality.md`

- [ ] **Step 1: Inspect `CustomVlmApiSettings`**

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
.venv/bin/python << 'PYEOF' 2>&1 | grep -v "Nutrient Licensing\|This is a demo\|compiled at\|Features:\|Copyright\|Welcome\|This version\|bundle identifier\|Guides &\|Already a\|^│\|^└\|^┌\|^$"
import os
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
with Document.open('tests/fixtures/input_ocr_multiple_languages.png') as d:
    cs = d.get_settings().get_custom_vlm_api_settings()
    print('CustomVlmApiSettings setters:')
    for m in sorted(dir(cs)):
        if m.startswith('set_'):
            print(f'  {m}')
PYEOF
```

Expected: a list of setters revealing what fields are configurable. Likely candidates: `api_endpoint`, `api_key`, `model`, `headers`.

- [ ] **Step 2: Check if there's a corresponding `VlmProvider.CUSTOM` enum value**

```bash
.venv/bin/python -c "
from nutrient_sdk.vlmprovider import VlmProvider
print([m for m in dir(VlmProvider) if not m.startswith('_')])
" 2>&1 | grep -v "Nutrient Licensing\|This is a demo\|compiled at\|Features:\|Copyright\|Welcome\|This version\|bundle identifier\|Guides &\|Already a\|^│\|^└\|^┌\|^$"
```

Expected: `['CLAUDE', 'OPENAI', 'CUSTOM']` or similar. If `CUSTOM` is absent, the settings might be unreachable.

- [ ] **Step 3: Try driving a self-hosted endpoint (only if Step 2 reveals a usable provider)**

If `VlmProvider.CUSTOM` exists, run a quick check pointing at a localhost endpoint. The user does not need to actually have LM Studio running — the goal is to see whether the SDK *attempts* the call (vs. failing earlier). If the call attempts and fails with a connection error, the integration works.

```bash
.venv/bin/python << 'PYEOF' 2>&1 | tail -20
import os
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, Vision
from nutrient_sdk.vlmprovider import VlmProvider
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
IMG = 'tests/fixtures/input_ocr_multiple_languages.png'
try:
    with Document.open(IMG) as d:
        s = d.get_settings()
        s.get_custom_vlm_api_settings().set_api_endpoint('http://localhost:1234/v1/')
        s.get_custom_vlm_api_settings().set_api_key('not-used')
        s.get_vision_settings().set_provider(VlmProvider.CUSTOM)
        out = Vision.set(d).describe()
        print('SUCCESS:', out[:200])
except Exception as e:
    print(f'EXPECTED FAIL: {type(e).__name__}: {str(e)[:300]}')
PYEOF
```

If `CUSTOM` isn't a valid provider, this step will fail at the `set_provider` line. Note that in the finding.

- [ ] **Step 4: Document**

Append under the "Follow-up investigations (2026-05-29)" section:

```markdown
### `CustomVlmApiSettings` for self-hosted VLM endpoints

`DocumentSettings.get_custom_vlm_api_settings()` exposes [enumerate the setters from Step 1].

`VlmProvider` values available: [paste from Step 2].

[If CUSTOM provider exists and accepts the endpoint:]
**Verdict:** The SDK supports BYO VLM via `VlmProvider.CUSTOM`. Customers who need an air-gapped or proprietary model can plug it in here. This is a real value proposition that isn't surfaced in the comparison doc — worth highlighting to the SDK team and adding to the public demo.

[If CUSTOM provider does not exist:]
**Verdict:** `CustomVlmApiSettings` exists in the settings tree but there is no `VlmProvider.CUSTOM` enum value to route to it. Either an unfinished feature or a settings-layer fossil — worth a clarifying note to the SDK team.
```

- [ ] **Step 5: Commit**

```bash
git add docs/sdk-feedback/2026-05-28-icr-engine-quality.md
git commit -m "docs(icr): document CustomVlmApiSettings investigation"
```

---

## Task 4: Multi-language ICR

**Hypothesis:** `OcrSettings.default_languages` defaults to `'eng'`. ICR's poor performance on the test corpus might be specifically poor on English cursive rather than uniformly poor. A non-English handwriting sample with the language explicitly set should clarify.

**Files:**
- Modify: `docs/sdk-feedback/2026-05-28-icr-engine-quality.md`
- Optional: `tests/test_extraction.py`

- [ ] **Step 1: Check what language codes the SDK accepts**

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
.venv/bin/python << 'PYEOF' 2>&1 | grep -v "Nutrient Licensing\|This is a demo\|compiled at\|Features:\|Copyright\|Welcome\|This version\|bundle identifier\|Guides &\|Already a\|^│\|^└\|^┌\|^$"
import os
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
with Document.open('tests/fixtures/input_ocr_multiple_languages.png') as d:
    o = d.get_settings().get_ocr_settings()
    print('default_languages:', o.get_default_languages())
    # check for an enum or validator method
    print('OcrSettings methods:')
    for m in sorted(dir(o)):
        if not m.startswith('_'):
            print(' ', m)
PYEOF
```

Expected: the current value `'eng'`, plus a method list. There may not be a way to enumerate valid codes — they're likely ISO 639-2 strings (e.g. 'spa', 'fra', 'deu', 'jpn').

- [ ] **Step 2: Run ICR on the multi-language fixture with English default**

```bash
.venv/bin/python << 'PYEOF' > /tmp/task4-eng.txt 2>&1
import os, json
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, Vision, VisionEngine, VisionFeatures
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
IMG = 'tests/fixtures/input_ocr_multiple_languages.png'
with Document.open(IMG) as d:
    s = d.get_settings()
    s.get_vision_settings().set_engine(VisionEngine.ICR)
    s.get_vision_settings().set_features(VisionFeatures.ALL.value - VisionFeatures.FORM.value)
    raw = Vision.set(d).extract_content()
parsed = json.loads(raw)
elements = sorted(parsed.get('elements', []), key=lambda e: e.get('readingOrder', 0))
text = '\n'.join(e.get('text', '').strip() for e in elements if e.get('text', '').strip())
print(text)
PYEOF
head -c 1500 /tmp/task4-eng.txt
```

Expected: text from `input_ocr_multiple_languages.png`. Note which languages are recognized vs garbled.

- [ ] **Step 3: Re-run with multi-language codes**

```bash
.venv/bin/python << 'PYEOF' > /tmp/task4-multi.txt 2>&1
import os, json
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, Vision, VisionEngine, VisionFeatures
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
IMG = 'tests/fixtures/input_ocr_multiple_languages.png'
with Document.open(IMG) as d:
    s = d.get_settings()
    s.get_vision_settings().set_engine(VisionEngine.ICR)
    s.get_vision_settings().set_features(VisionFeatures.ALL.value - VisionFeatures.FORM.value)
    # Try common ISO 639-2 codes for Western European languages
    s.get_ocr_settings().set_default_languages('eng+fra+spa+deu')
    raw = Vision.set(d).extract_content()
parsed = json.loads(raw)
elements = sorted(parsed.get('elements', []), key=lambda e: e.get('readingOrder', 0))
text = '\n'.join(e.get('text', '').strip() for e in elements if e.get('text', '').strip())
print(text)
PYEOF
head -c 1500 /tmp/task4-multi.txt
```

If `set_default_languages` rejects the format, the error message will reveal the expected syntax (try `'eng,fra,spa,deu'` next, or `['eng', 'fra', 'spa', 'deu']`).

- [ ] **Step 4: Diff the two outputs**

```bash
diff -u /tmp/task4-eng.txt /tmp/task4-multi.txt | head -40
```

- [ ] **Step 5: Document**

Append:

```markdown
### Multi-language ICR

`OcrSettings.default_languages` accepts [the format determined in Step 3 — paste an example].

Tested on `tests/fixtures/input_ocr_multiple_languages.png` (filename suggests it contains multiple language scripts).

**With default `'eng'`:** [paste 400 chars of /tmp/task4-eng.txt]

**With `'eng+fra+spa+deu'` (or whatever syntax worked):** [paste 400 chars of /tmp/task4-multi.txt]

**Verdict:** [Multi-language config improves recognition on non-English text | Multi-language config has no observable effect | Multi-language config errors / is silently ignored]
```

- [ ] **Step 6: Commit**

```bash
git add docs/sdk-feedback/2026-05-28-icr-engine-quality.md
git commit -m "docs(icr): document multi-language ICR investigation"
```

---

## Task 5: `AiAugmenter` toggles

**Hypothesis:** `AiAugmenterSettings` has six enable flags (`enable_content_description`, `enable_language_detection`, `enable_reading_order`, `enable_relationship_detection`, `enable_vlm_classification`, plus `classification_confidence`). All default ON. We have not characterized what each contributes to the output.

**Files:**
- Modify: `docs/sdk-feedback/2026-05-28-icr-engine-quality.md`

- [ ] **Step 1: Capture baseline ICR output with all augmenters enabled**

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
.venv/bin/python << 'PYEOF' > /tmp/task5-all-on.json 2>&1
import os, json
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, Vision, VisionEngine, VisionFeatures
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
IMG = 'recipes/handwritten/se6kza6795yg1.jpeg'
with Document.open(IMG) as d:
    s = d.get_settings()
    s.get_vision_settings().set_engine(VisionEngine.ICR)
    s.get_vision_settings().set_features(VisionFeatures.ALL.value - VisionFeatures.FORM.value)
    raw = Vision.set(d).extract_content()
print(raw)
PYEOF
python3 -m json.tool /tmp/task5-all-on.json | head -60
```

Expected: full JSON of detected elements. Note which fields appear: `text`, `confidence`, `language`, `readingOrder`, `relationships`, `classification`, etc.

- [ ] **Step 2: Disable each augmenter individually and diff the JSON shape**

```bash
for flag in enable_content_description enable_language_detection enable_reading_order enable_relationship_detection enable_vlm_classification; do
  .venv/bin/python << PYEOF > /tmp/task5-off-${flag}.json 2>&1
import os, json
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, Vision, VisionEngine, VisionFeatures
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
IMG = 'recipes/handwritten/se6kza6795yg1.jpeg'
with Document.open(IMG) as d:
    s = d.get_settings()
    s.get_vision_settings().set_engine(VisionEngine.ICR)
    s.get_vision_settings().set_features(VisionFeatures.ALL.value - VisionFeatures.FORM.value)
    getattr(s.get_ai_augmenter_settings(), 'set_${flag}')(False)
    raw = Vision.set(d).extract_content()
print(raw)
PYEOF
  echo "--- with ${flag}=False ---"
  python3 -c "
import json
a = json.load(open('/tmp/task5-all-on.json'))
b = json.load(open('/tmp/task5-off-${flag}.json'))
ka = set()
kb = set()
for e in a.get('elements', []):
    ka.update(e.keys())
for e in b.get('elements', []):
    kb.update(e.keys())
print('removed:', sorted(ka - kb))
print('added:', sorted(kb - ka))
"
done
```

Expected: for each disabled augmenter, a list of JSON fields that disappear (or appear). This is the empirical map of what each augmenter contributes.

- [ ] **Step 3: Document**

Append:

```markdown
### What does each `AiAugmenter` toggle actually add?

Default ICR output on `recipes/handwritten/se6kza6795yg1.jpeg` includes the following JSON element keys: [paste sorted list from Step 1].

Toggling each augmenter off (one at a time) removed or changed these fields:

| Toggle | Fields removed | Fields added |
|---|---|---|
| `enable_content_description=False` | [paste] | [paste] |
| `enable_language_detection=False` | [paste] | [paste] |
| `enable_reading_order=False` | [paste] | [paste] |
| `enable_relationship_detection=False` | [paste] | [paste] |
| `enable_vlm_classification=False` | [paste] | [paste] |

**Notes:** [Any observations — e.g., one augmenter accounts for most of the JSON surface, or one is a no-op, or one removes fields a customer would expect from a different API]
```

- [ ] **Step 4: Commit**

```bash
git add docs/sdk-feedback/2026-05-28-icr-engine-quality.md
git commit -m "docs(icr): map AiAugmenter toggles to JSON output fields"
```

---

## Task 6: Form detection on an already-fielded PDF

**Hypothesis:** `PdfEditor.detect_and_add_form_fields()` is documented for adding fields to an unfielded PDF. What happens if the input already has form fields? Duplicates? Skipped? Crash?

**Files:**
- Modify: `docs/sdk-feedback/2026-05-28-icr-engine-quality.md` (or a new note in `docs/sdk-feedback/2026-05-28-form-field-detection-quality.md` if that file feels more appropriate — pick by reading both first)

- [ ] **Step 1: Run detection on a fielded PDF**

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
.venv/bin/python << 'PYEOF' 2>&1 | grep -v "Nutrient Licensing\|This is a demo\|compiled at\|Features:\|Copyright\|Welcome\|This version\|bundle identifier\|Guides &\|Already a\|^│\|^└\|^┌\|^$"
import os
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License, Document, PdfEditor
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])

PDF = 'tests/fixtures/account-registration-form.pdf'

# Count fields BEFORE
with Document.open(PDF) as d:
    e = PdfEditor.edit(d)
    before = e.get_form_field_collection().get_count()
    print(f'BEFORE detection: {before} fields')
    before_names = [e.get_form_field_collection()[i].get_full_name() for i in range(before)]
    e.close()

# Run detect_and_add_form_fields on the same PDF
with Document.open(PDF) as d:
    e = PdfEditor.edit(d)
    try:
        e.detect_and_add_form_fields()
        after = e.get_form_field_collection().get_count()
        print(f'AFTER detection: {after} fields')
        after_names = [e.get_form_field_collection()[i].get_full_name() for i in range(after)]
        added = set(after_names) - set(before_names)
        removed = set(before_names) - set(after_names)
        duplicated = [n for n in after_names if after_names.count(n) > 1]
        print(f'Added: {sorted(added)}')
        print(f'Removed: {sorted(removed)}')
        print(f'Duplicates (appearing 2+ times): {sorted(set(duplicated))}')
        e.save_as('/tmp/task6-after-detection.pdf')
    except Exception as ex:
        print(f'FAIL: {type(ex).__name__}: {ex}')
    finally:
        e.close()
PYEOF
```

Expected: BEFORE prints ~15 (the form-fill demo PDF has 15 fields). AFTER prints one of:
- Same count, same names → detection is idempotent / skipped
- Higher count, no duplicate names → new fields added in addition to existing
- Higher count with duplicates → duplicates added blindly
- Crash → defect

- [ ] **Step 2: Open the resulting PDF visually (optional)**

```bash
open /tmp/task6-after-detection.pdf
```

If duplicates are present visually, confirm they overlap the existing fields or are placed elsewhere on the page.

- [ ] **Step 3: Document**

Append:

```markdown
### Form detection on an already-fielded PDF

Ran `PdfEditor.detect_and_add_form_fields()` against the form-fill demo PDF (`tests/fixtures/account-registration-form.pdf`), which already has 15 form fields:

- **Before:** [paste before count and a sample of field names]
- **After:** [paste after count, added names, duplicate count]

**Verdict:** [Detection on a fielded PDF is idempotent and safe | Detection blindly adds new fields, creating duplicates | Detection crashes / errors]

**Customer impact:** [If duplicates: applications that allow re-detection without deduplication will accumulate junk fields over time. Recommend either (a) the SDK should skip regions where a field already exists, or (b) document that callers must clear existing fields before re-detecting.]
```

- [ ] **Step 4: Commit**

```bash
git add docs/sdk-feedback/2026-05-28-icr-engine-quality.md
git commit -m "docs(forms): document detect_and_add_form_fields behavior on fielded PDFs"
```

---

## Task 7: Retest `_vision_keep_alive` workaround

**Hypothesis:** `app/services/extraction.py:9` retains every `Vision` object to dodge a native-GC SIGSEGV from earlier SDK versions. The bug may be fixed on 1.0.6. If so, the unbounded list can be removed.

**Files:**
- Modify (conditional): `app/services/extraction.py`
- Modify: `docs/sdk-feedback/2026-05-28-icr-engine-quality.md`
- Modify (conditional): `tests/test_extraction.py`

- [ ] **Step 1: Reproduce a stress run with the workaround in place (baseline)**

```bash
cd /Users/jonaddamsnutrient/SE/code/python-fast-api
.venv/bin/python << 'PYEOF' 2>&1 | tail -5
import os, json
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
from app.services.extraction import extract_text_ocr, extract_text_icr

img = open('tests/fixtures/input_ocr_multiple_languages.png', 'rb').read()
for i in range(30):
    extract_text_ocr(img, 'in.png')
    if i % 5 == 0: print(f'  ocr iter {i} done')
for i in range(30):
    extract_text_icr(img, 'in.png')
    if i % 5 == 0: print(f'  icr iter {i} done')
print('baseline stress run complete')
PYEOF
```

Expected: completes without crash. If it doesn't even succeed with the workaround in place, abort the rest of this task and report findings.

- [ ] **Step 2: Remove the keep-alive list**

In `app/services/extraction.py`, replace this block (currently around lines 7–20):

```python
# SDK bug: native Close() on Vision objects SIGSEGV's on GC.
# Retain references to prevent cleanup.
_vision_keep_alive: list[Vision] = []
```

With:

```python
# `_vision_keep_alive` removed 2026-05-29 after retest on nutrient-sdk
# 1.0.6 showed the native GC SIGSEGV no longer reproduces. Re-add if
# segfaults reappear.
```

And remove every `_vision_keep_alive.append(vision)` line in the file (likely 1–2 places — confirm via grep first):

```bash
grep -n "_vision_keep_alive" app/services/extraction.py
```

Remove each appearance (the `append()` line, not the whole function — keep `vision = Vision.set(doc)` and `raw_json = vision.extract_content()`).

- [ ] **Step 3: Stress-run without the workaround**

```bash
.venv/bin/python << 'PYEOF' 2>&1 | tail -5
import os, json
from dotenv import load_dotenv
load_dotenv('.env')
from nutrient_sdk import License
License.register_key(os.environ['NUTRIENT_LICENSE_KEY'])
from app.services.extraction import extract_text_ocr, extract_text_icr

img = open('tests/fixtures/input_ocr_multiple_languages.png', 'rb').read()
for i in range(50):
    extract_text_ocr(img, 'in.png')
for i in range(50):
    extract_text_icr(img, 'in.png')
print('post-removal stress run complete')
PYEOF
```

Expected outcomes:
- **Clean (no crash):** The workaround is no longer needed. Keep the removal.
- **SIGSEGV / process killed:** The bug persists on 1.0.6. Revert the removal (`git checkout -- app/services/extraction.py`) and document the result.

- [ ] **Step 4: Run the full test suite**

```bash
make test
```

Expected: 9 passed (existing count) if the removal was clean.

- [ ] **Step 5: Document the outcome**

Append:

```markdown
### `_vision_keep_alive` workaround status on 1.0.6

A module-level list `_vision_keep_alive` in `app/services/extraction.py` retained every `Vision` object to dodge a native-GC SIGSEGV from earlier SDK versions. Retested on 1.0.6:

- **Stress run (50× OCR + 50× ICR sequentially) with workaround:** [completed cleanly / crashed]
- **Stress run with workaround removed:** [completed cleanly / crashed at iteration N]

**Verdict:** [Bug fixed on 1.0.6 — workaround removed in this commit | Bug still present on 1.0.6 — workaround retained, recommend SDK team look into native-GC handling of Vision objects]
```

- [ ] **Step 6: Commit**

If removal was clean:

```bash
git add app/services/extraction.py docs/sdk-feedback/2026-05-28-icr-engine-quality.md
git commit -m "fix(extraction): remove _vision_keep_alive workaround

Stress-tested 50x OCR + 50x ICR calls on nutrient-sdk 1.0.6 without
the keep-alive list - the native-GC SIGSEGV that motivated this
workaround no longer reproduces."
```

If the bug still reproduces:

```bash
git checkout -- app/services/extraction.py
git add docs/sdk-feedback/2026-05-28-icr-engine-quality.md
git commit -m "docs(extraction): confirm _vision_keep_alive still needed on 1.0.6"
```

---

## Task 8: Open the PR

- [ ] **Step 1: Push and open**

```bash
git push -u origin icr-followup-investigations
gh pr create --title "Follow-up ICR investigations (7 items)" --body "$(cat <<'EOF'
## Summary
Executes the seven follow-up investigations from the ICR feedback work:

1. `Vision.describe()` with a custom prompt
2. OpenAI VLM provider parity
3. `CustomVlmApiSettings` (self-hosted VLM endpoints)
4. Multi-language ICR
5. `AiAugmenter` toggles — what each one actually contributes
6. Form detection on an already-fielded PDF
7. `_vision_keep_alive` workaround status on 1.0.6

All findings appended to `docs/sdk-feedback/2026-05-28-icr-engine-quality.md` under a new "Follow-up investigations (2026-05-29)" section. Task 1 and Task 7 may have produced code changes (a new `/api/extraction/describe` endpoint and/or removal of the keep-alive workaround); see commits.

## Test plan
- [x] All commands in each task's steps executed and outputs captured
- [x] `make test` — passing on the final commit
- [x] Findings documented with verbatim output excerpts

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Out of scope (do NOT pick up in this plan)

- **A 50-image structured ICR benchmark with confidence intervals.** Flagged as a separate larger effort in the comparison doc's caveats. Would require source-of-truth transcriptions for each image and a real evaluation harness.
- **Competing-API benchmarks (Google Document AI, AWS Textract, Azure Document Intelligence).** Listed in the engineering feedback section but is a separate procurement / API-key effort outside this plan.
- **New frontend pages for any of these investigations.** The demo page work landed in earlier PRs. Add new pages only if a finding here demonstrably warrants one (e.g., Task 1 produces a working transcribe path — that could merit a dedicated UI follow-up, but it's not in scope for this plan).
