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
| `ANTHROPIC_API_KEY` | Optional, for `Vision.describe()` via Claude | — |
| `OPENAI_API_KEY` | Optional, for `Vision.describe()` via OpenAI | — |

## Running

```bash
make dev        # uvicorn with --reload on port 8080
make test       # full pytest suite (~3–4 min with API keys set (many tests make live VLM/Claude calls); tests requiring absent keys are skipped)
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
| `conversion` | `POST /api/conversion/...` | Office ↔ PDF, Markdown → PDF, PDF → HTML |
| `editor` | `POST /api/editor/...` | PDF editing primitives |
| `forms` | `POST /api/forms/list-fields` | Enumerate existing form fields |
| `forms` | `POST /api/forms/fill-fields` | Fill named fields with values |
| `forms` | `POST /api/forms/detect?confidence=0.75` | ML form-field detection |
| `signing` | `POST /api/signing/sign-demo` | Demo digital signature with bundled cert |
| `signing` | `POST /api/signing/sign` | Digital signature with user-supplied cert |
| `extraction` | `POST /api/extraction/ocr` | OCR text extraction |
| `extraction` | `POST /api/extraction/icr` | ICR (handwriting) extraction |
| `extraction` | `POST /api/extraction/vlm` | VLM-enhanced ICR (`?provider=claude\|openai`; defaults to localhost:1234) |
| `extraction` | `POST /api/extraction/describe` | Custom-prompt transcription / alt-text (`level=standard\|detailed`) |
| `extraction` | `POST /api/extraction/tables` | Structured table extraction (VLM + Claude/OpenAI) |
| `extraction` | `POST /api/extraction/markdown` | Document → clean Markdown for RAG/LLM ingestion |
| `extraction` | `POST /api/extraction/fields` | Key-value extraction: native regions + schema-driven JSON |
| `templates` | `POST /api/templates/...` | Word template generation |
| `redaction` | `POST /api/redaction/...` | Permanent content redaction |

The OpenAPI spec at `/docs` is the source of truth for parameter shapes.

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
docs/
  sdk-feedback/      # Findings to share with the Nutrient SDK team
```
