# Nutrient Python SDK — FastAPI Demo Backend

A FastAPI service that wraps the [Nutrient Python SDK](https://www.nutrient.io/sdk/python/) for document processing — conversion, OCR/ICR/VLM extraction, digital signing, form-field detection and fill, redaction, and Word template generation.

Pairs with the [`nutrient-sdk-samples`](https://github.com/jonaddams/nutrient-sdk-samples) Next.js frontend.

## Requirements

- Python 3.12+
- A Nutrient license key with the entitlements you want to demo. The Vision (extraction) and form-detection features require additional features beyond a base license — see [Nutrient's licensing docs](https://www.nutrient.io/guides/python/) for specifics.

## Setup

```bash
git clone https://github.com/jonaddams/python-fast-api.git
cd python-fast-api

python3.12 -m venv .venv
make install

cp .env.example .env
# Edit .env and paste your NUTRIENT_LICENSE_KEY
```

`.env` recognized variables:

| Variable | Purpose | Default |
|---|---|---|
| `NUTRIENT_LICENSE_KEY` | Nutrient SDK license (required) | — |
| `ALLOWED_ORIGINS` | CORS origins for the frontend, comma-separated | `http://localhost:3000` |
| `PORT` | uvicorn bind port (used by `app.config`, not the Makefile) | `8080` |
| `ANTHROPIC_API_KEY` | Optional, for `Vision.describe()` via Claude, and for `structured` with `provider=anthropic` (alias `claude`) | — |
| `OPENAI_API_KEY` | Optional, for `Vision.describe()` via OpenAI, and for `structured` with `provider=openai` | — |
| `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_ENDPOINT` | Optional, for `structured` with `provider=azure` | — |
| `BEDROCK_API_KEY` | Optional, long-term Bedrock API key, for `structured` with `provider=bedrock`. Also gates whether `bedrock` appears in `GET /api/extraction/providers`. | — |
| `BEDROCK_ENDPOINT` | Optional override for the Bedrock OpenAI-compatible endpoint (must end in `/v1`) | `https://bedrock-mantle.$AWS_REGION.api.aws/v1` |
| `AWS_REGION` | Shapes the default Bedrock endpoint | `us-east-1` |
| `LM_STUDIO_API_URL` | Optional, for `structured` with `provider=local`. Set locally only — its presence is what lists the `local` option. | `http://localhost:1234/v1` |
| `OPENAI_STRUCTURED_MODEL` / `AZURE_STRUCTURED_MODEL` / `ANTHROPIC_STRUCTURED_MODEL` / `BEDROCK_STRUCTURED_MODEL` / `LM_STUDIO_MODEL` | Optional model overrides for `structured`. A Bedrock override must be one of the two ids in the server-side allowlist (see `GET /api/extraction/providers`) or the process fails to start. | `gpt-5.4` / `gpt-5.4` / `claude-sonnet-5` / `qwen.qwen3-vl-235b-a22b` / `local-model` |

## Running

```bash
make dev        # uvicorn with --reload on port 8080
make test       # full pytest suite, ~6 min (many tests make live VLM/Claude calls; tests for absent keys are skipped)
make install    # re-sync the editable install with pyproject.toml
make help       # list targets
```

Override the dev port: `make dev PORT=9000`.

Once `make dev` is running:

- `http://localhost:8080/docs` — FastAPI Swagger UI for every endpoint
- `http://localhost:8080/api/health` — health check

To pair with the frontend, in the `nutrient-sdk-samples` repo:

```bash
NEXT_PUBLIC_PYTHON_SDK_API_URL=http://localhost:8080 npm run dev
```

Then visit `http://localhost:3000/python-sdk`.

## Endpoints

Routers live under `app/routers/`. Each delegates to a service in `app/services/`.

| Router | Endpoint | Purpose |
|---|---|---|
| `health` | `GET /api/health` | Liveness check |
| `extraction` | `GET /api/extraction/providers` | Which `structured` providers/models this deployment can serve, decided from credential presence |
| `conversion` | `POST /api/conversion/...` | Office ↔ PDF, Markdown → PDF, PDF → HTML |
| `editor` | `POST /api/editor/...` | PDF editing primitives |
| `forms` | `POST /api/forms/list-fields` | Enumerate existing form fields |
| `forms` | `POST /api/forms/fill-fields` | Fill named fields with values |
| `forms` | `POST /api/forms/detect?confidence=0.75` | ML form-field detection |
| `signing` | `POST /api/signing/sign-demo` | Demo digital signature with bundled cert |
| `signing` | `POST /api/signing/sign` | Digital signature with user-supplied cert |
| `extraction` | `POST /api/extraction/ocr` | OCR text extraction |
| `extraction` | `POST /api/extraction/icr` | ICR (handwriting) extraction |
| `extraction` | `POST /api/extraction/vlm` | VLM-enhanced ICR (`?provider=claude\|openai`; falls back to localhost:1234 when unset) |
| `extraction` | `POST /api/extraction/describe` | Custom-prompt transcription / alt-text (`level=standard\|detailed`) |
| `extraction` | `POST /api/extraction/tables` | Structured table extraction (VLM + Claude/OpenAI) |
| `extraction` | `POST /api/extraction/markdown` | Document → clean Markdown for RAG/LLM ingestion |
| `extraction` | `POST /api/extraction/fields` | Key-value extraction: native regions + schema-driven JSON |
| `extraction` | `POST /api/extraction/structured` | Schema-driven extraction via the SDK's native `Vision.extract_structured()`, with grounded source rectangles and confidence (`?provider=openai\|azure\|anthropic\|bedrock\|local`) |
| `templates` | `POST /api/templates/...` | Word template generation |
| `redaction` | `POST /api/redaction/...` | Permanent content redaction |

The OpenAPI spec at `/docs` is the source of truth for parameter shapes.

Scanned/image-only PDFs are pre-rendered page-by-page: the `ocr`, `icr`, `vlm`, `tables`,
and `markdown` endpoints process up to 10 pages per request and report `totalPages` /
`processedPages` in the response (truncation is visible, never silent). The `describe` and
`fields` endpoints operate on page 1 by design.

**`structured` vs `fields`** — they look similar and are not. `fields` hand-writes a VLM prompt
asking for JSON and post-parses the reply, so it also returns the SDK's native
`KEY_VALUE_REGION` output for comparison. `structured` calls the SDK's own
`Vision.extract_structured()` with a real JSON schema, so the SDK returns grounded source
rectangles and confidence components rather than prose we parse. Prefer `structured` when you
want citations you can draw on the page; `fields` is the "here's what a prompt gets you"
counterpart. Unlike the pre-rendering endpoints above, `structured` passes the **original**
document to the SDK — rasterizing first would discard the text layer and the page coordinates
its bounding boxes are expressed in. It requires the `vision_vlm_data_extraction_api`
entitlement; without it the SDK returns error 3017.

## Tests

Integration tests live in `tests/`, hitting the real SDK via `fastapi.testclient.TestClient` (no mocks). Fixtures are in `tests/fixtures/`.

```bash
make test                                       # everything
.venv/bin/pytest tests/test_forms_detect.py -v  # one file
.venv/bin/pytest -k detect -v                   # filter by name
```

Pytest's `faulthandler` plugin is disabled in `pyproject.toml` because `nutrient-sdk-native` raises `SIGSEGV` internally during ML inference. Don't remove that line unless you've confirmed the SDK no longer needs it.

## Project layout

```
app/
  main.py            # FastAPI app, license registration, CORS, router includes
  config.py          # .env loading
  routers/           # Thin HTTP handlers
  services/          # SDK interaction
  certs/             # Demo signing certificate
tests/
  conftest.py        # Shared FastAPI test client + fixtures
  fixtures/          # Sample PDFs and images
```
