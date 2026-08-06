"""Schema-driven structured extraction via the SDK's native Vision API.

Distinct from the `fields` path in services/extraction.py, which hand-writes a
VLM prompt and post-parses the model's JSON reply. This calls the SDK's own
`Vision.extract_structured()` with a real JSON schema, so the SDK returns
grounded source locations and confidence components rather than prose we parse.

Deliberately does NOT use `_prepared_pages`/`_prepared_input` from
services/extraction.py. Those pre-render a PDF to per-page JPEGs for Vision's
image path; structured extraction needs the ORIGINAL document so the SDK can
read its text layer and report bounding boxes in page coordinates. Rasterizing
first would discard both. Page images, when wanted, are requested through
`include_page_images` and handled inside the SDK.
"""

import contextlib
import json
import os
import tempfile
import time
from typing import Any, Iterator

from pydantic import BaseModel

# Model defaults per provider. Overridable via env so a demo can point at
# whatever is current without a code change.
_DEFAULT_MODELS = {
    "openai": os.environ.get("OPENAI_STRUCTURED_MODEL", "gpt-5.4"),
    "azure": os.environ.get("AZURE_STRUCTURED_MODEL", "gpt-5.4"),
    "local": os.environ.get("LM_STUDIO_MODEL", "local-model"),
    # An explicit model is REQUIRED on this path. Unlike ClaudeApiSettings (which
    # defaults to claude-sonnet-4-6), the flat ai.provider/ai.model connection has
    # no default, and omitting it fails with "AiProcessing model is required" —
    # which reads like the provider is unsupported when it is not.
    # claude-sonnet-5 verified working against extract_structured(), including
    # grounded citations, 2026-08-04.
    "anthropic": os.environ.get("ANTHROPIC_STRUCTURED_MODEL", "claude-sonnet-5"),
    # Bedrock model ids are not recognised by the SDK, which is why requests on this
    # path carry logprobs/top_logprobs. Ids verified live against the real
    # Bedrock catalogue 2026-08-04: see the comment on _ALLOWED_MODELS below.
    "bedrock": os.environ.get(
        "BEDROCK_STRUCTURED_MODEL", "qwen.qwen3-vl-235b-a22b-instruct"
    ),
}
_FALLBACK_MODEL = "gpt-5.4"

# Provider id -> the env var apply_provider() reads for ai.api_key. Kept next to
# _DEFAULT_MODELS on purpose: both are per-provider maps that _build_code() and
# apply_provider() must agree on, and keeping them side by side is what stops
# them from drifting apart when a provider is added or renamed. "local" has no
# entry because it authenticates with no key at all (endpoint only).
_API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "bedrock": "BEDROCK_API_KEY",
}

# "claude" is the documented alias for "anthropic" on ai.provider. Normalising
# means callers can send either and the config echo still names one thing.
_PROVIDER_ALIASES = {"claude": "anthropic"}

# Models a caller may request per provider. Providers absent from this map accept
# no `model` parameter at all and always use their env default.
#
# Two reasons this is an allowlist rather than a pass-through: a caller-supplied
# model combined with a configurable endpoint would turn /structured into a
# general-purpose proxy, and silently ignoring an unknown model would let someone
# select "Gemma 3 27B" in the UI and watch Qwen run.
#
# Ids verified live against the real Bedrock catalogue 2026-08-04
# (https://bedrock-mantle.us-east-1.api.aws/v1). Notes from that verification:
# - There are no amazon.nova-* models on this endpoint at all (GET /v1/models
#   returned 55 models, zero of them Nova) — the id previously here
#   (amazon.nova-pro-v1:0) does not exist and was replaced with Gemma.
# - GET /v1/models lists more than /v1/chat/completions accepts: e.g.
#   google.gemma-4-31b and anthropic.claude-sonnet-5 both appear in the
#   catalogue but are rejected on the chat-completions route. Catalogue
#   membership does not imply usability — only these two ids were confirmed
#   to actually work end to end.
_ALLOWED_MODELS: dict[str, set[str]] = {
    "bedrock": {"qwen.qwen3-vl-235b-a22b-instruct", "google.gemma-3-27b-it"},
}

# Human labels for the UI, so the model list has one source of truth.
_MODEL_LABELS: dict[str, str] = {
    "qwen.qwen3-vl-235b-a22b-instruct": "Qwen3-VL 235B",
    "google.gemma-3-27b-it": "Gemma 3 27B",
}


def _validate_default_models() -> None:
    """Fail loudly, at import time, if a provider's default model isn't a member
    of its own allowlist.

    Without this, e.g. setting BEDROCK_STRUCTURED_MODEL to a third id (exactly
    what live verification against the real catalogue invites) produces a
    silent, ugly failure: available_providers() publishes that id as
    `defaultModel`, the UI's controlled <select> renders only the allowlist and
    so falls back to displaying its first option, and the request sends no
    `model` at all — so whatever the env var names actually runs while the user
    watches a different model's name on screen. Raising here, at import, turns
    that into a startup error instead of a demo-time surprise.
    """
    for provider, allowed in _ALLOWED_MODELS.items():
        default = _DEFAULT_MODELS.get(provider)
        # raise, not assert: `python -O` / PYTHONOPTIMIZE strips assert
        # statements, which would silently remove this guard in exactly the
        # deployment most likely to run optimised.
        if default not in allowed:
            raise RuntimeError(
                f"{provider}'s default model {default!r} is not in its own "
                f"allowlist {sorted(allowed)}. Point the "
                f"{provider.upper()}_STRUCTURED_MODEL env var at one of those, or "
                "add the id to _ALLOWED_MODELS."
            )


_validate_default_models()


class UnsupportedModel(ValueError):
    """A caller asked for a model the provider does not offer. Mapped to 400."""


class ProviderNotConfigured(ValueError):
    """The chosen provider has no credentials in this deployment. Mapped to 400."""


class Citation(BaseModel):
    """A field's location on the page, in fractional page coordinates (0..1)."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class FieldResult(BaseModel):
    name: str
    type: str
    value: Any = None
    page: int | None = None
    confidence: float | None = None
    match: str | None = None
    citation: Citation | None = None


class StructuredData(BaseModel):
    fields: list[FieldResult]
    extraction: dict[str, Any]


class Envelope(BaseModel):
    """The response shape. Richer than this repo's other extraction endpoints
    because the consuming UI renders citations over the document and shows
    `code` as a copyable "here's how you'd do this yourself" snippet."""

    feature: str
    resultType: str
    config: dict[str, Any]
    timingMs: int
    filename: str
    data: dict[str, Any]
    raw: str
    code: str


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def normalize_bbox(raw: dict, page_w: float, page_h: float) -> dict:
    """Convert a raw SDK bbox {x, y, width, height} (raster pixels, origin
    top-left; the 'unit' field is unreliable and ignored) to fractional page
    coords in 0..1, where page_w/page_h are the raster px dims from the
    extraction's top-level `pages[]` array."""
    if page_w <= 0 or page_h <= 0:
        raise ValueError("page dimensions must be positive")
    x, y = float(raw["x"]), float(raw["y"])
    right, bottom = x + float(raw["width"]), y + float(raw["height"])
    return {
        "x0": _clamp01(x / page_w),
        "y0": _clamp01(y / page_h),
        "x1": _clamp01(right / page_w),
        "y1": _clamp01(bottom / page_h),
    }


@contextlib.contextmanager
def _prepared_document(file_bytes: bytes, original_filename: str) -> Iterator[str]:
    """Write the uploaded bytes to a temp file and yield its path.

    The suffix carries the original filename because the SDK detects format
    from the extension. No rasterizing — see this module's docstring.
    """
    with tempfile.NamedTemporaryFile(
        suffix="-" + original_filename, delete=False
    ) as fh:
        fh.write(file_bytes)
        path = fh.name
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


def validate_provider_and_model(provider: str, model: str | None) -> str:
    """Reject an unusable provider/model pair BEFORE any document work.

    Called at the top of extract_structured() so a bad request costs nothing: the
    alternative is parsing the whole PDF under the license, then raising. It also
    keeps the 400-path tests free of any SDK dependency.

    This is the ONE place the allowlist and credential checks live; apply_provider()
    calls it too rather than keeping its own copy, so the two can't drift apart.

    Returns the normalised provider name (post `_PROVIDER_ALIASES` lookup).
    """
    provider = _PROVIDER_ALIASES.get(provider.lower(), provider.lower())
    allowed = _ALLOWED_MODELS.get(provider, set())
    if model:
        if not allowed:
            raise UnsupportedModel(
                f"provider {provider!r} does not accept a model parameter; "
                "omit it to use the configured default"
            )
        if model not in allowed:
            raise UnsupportedModel(
                f"model {model!r} is not available for provider {provider!r}; "
                f"allowed: {', '.join(sorted(allowed))}"
            )
    if provider == "bedrock" and not os.environ.get("BEDROCK_API_KEY", "").strip():
        raise ProviderNotConfigured(
            "BEDROCK_API_KEY is not configured on this backend; "
            "see GET /api/extraction/providers for what is available"
        )
    return provider


def apply_provider(ai, provider: str, model: str | None = None) -> dict:
    """Point ai_processing_settings at the chosen provider; return a config echo."""
    provider = validate_provider_and_model(provider, model)
    model = model or _DEFAULT_MODELS.get(provider, _FALLBACK_MODEL)
    ai.provider = provider
    ai.model = model
    echo: dict[str, Any] = {"provider": provider, "model": model}
    if provider == "openai":
        ai.api_key = os.environ.get("OPENAI_API_KEY", "")
    elif provider == "azure":
        ai.api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        ai.endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        echo["endpoint"] = ai.endpoint
    elif provider == "anthropic":
        # Endpoint left unset: the SDK defaults to https://api.anthropic.com/v1/.
        # Without this branch an unknown provider fell through to _FALLBACK_MODEL
        # and NO api_key, i.e. an OpenAI model id sent to Anthropic with no
        # credentials — a confusing failure rather than an honest one.
        ai.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    elif provider == "bedrock":
        # Bedrock's OpenAI-compatible surface. ai.provider becomes "openai" because
        # the SDK rejects every other value on this path; only the endpoint and key
        # differ. The trailing /v1 is REQUIRED — the SDK appends "/chat/completions"
        # verbatim. Bearer auth replaces SigV4 entirely, so AWS_ACCESS_KEY_ID and
        # AWS_SECRET_ACCESS_KEY are not used here.
        ai.provider = "openai"
        region = os.environ.get("AWS_REGION", "us-east-1")
        ai.endpoint = os.environ.get(
            "BEDROCK_ENDPOINT", f"https://bedrock-mantle.{region}.api.aws/v1"
        )
        # validate_provider_and_model() already confirmed BEDROCK_API_KEY is set.
        ai.api_key = os.environ.get("BEDROCK_API_KEY", "")
        echo["endpoint"] = ai.endpoint
    elif provider == "local":
        ai.endpoint = os.environ.get("LM_STUDIO_API_URL", "http://localhost:1234/v1")
        echo["endpoint"] = ai.endpoint
    return echo


# Provider id -> (display label, env var whose presence means "usable").
# Order here is the order the UI shows.
_PROVIDER_REGISTRY: list[tuple[str, str, str]] = [
    ("openai", "OpenAI", "OPENAI_API_KEY"),
    ("anthropic", "Claude", "ANTHROPIC_API_KEY"),
    ("bedrock", "AWS Bedrock", "BEDROCK_API_KEY"),
    ("local", "Local (LM Studio)", "LM_STUDIO_API_URL"),
]


def available_providers() -> list[dict]:
    """Providers this backend can actually serve, so the UI shows no dead options.

    Presence of the credential env var is the whole test — deliberately no network
    probe. LM_STUDIO_API_URL is set locally and never in Railway, which is what
    makes the Local option appear on a laptop and vanish when hosted. Note that
    apply_provider() keeps its own localhost fallback for that var, so a direct API
    call still behaves as it always has; only *listing* requires it.
    """
    providers: list[dict] = []
    for provider_id, label, env_var in _PROVIDER_REGISTRY:
        # .strip() for PARITY with validate_provider_and_model(), which strips
        # before deciding a provider is configured. Without it a whitespace-only
        # key listed the provider here and then 400'd on Run — the dropdown and
        # the request disagreeing about the same env var.
        if not os.environ.get(env_var, "").strip():
            continue
        models = sorted(_ALLOWED_MODELS.get(provider_id, set()))
        providers.append(
            {
                "id": provider_id,
                "label": label,
                "models": [
                    {"id": m, "label": _MODEL_LABELS.get(m, m)} for m in models
                ],
                "defaultModel": _DEFAULT_MODELS.get(provider_id, _FALLBACK_MODEL),
            }
        )
    return providers


def _kind_of(value: Any) -> str:
    # bool before int: bool is an int subclass in Python.
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def parse_structured(raw_json: str, filename: str) -> StructuredData:
    """Turn the SDK's raw extraction JSON into fields with page-relative citations."""
    payload = json.loads(raw_json)
    extraction: dict[str, Any] = payload.get("extraction", {})
    metadata: dict[str, Any] = payload.get("metadata", {})
    # raster dims per 1-based page number, straight from the SDK payload
    page_dims = {p["page"]: (p["width"], p["height"]) for p in payload.get("pages", [])}

    fields: list[FieldResult] = []
    for name, value in extraction.items():
        meta = metadata.get(name, {}) or {}
        page_1 = meta.get("page")
        page_0 = (page_1 - 1) if isinstance(page_1, int) else None
        citation = None
        box = meta.get("bbox")
        if box and page_1 in page_dims:
            w, h = page_dims[page_1]
            citation = Citation(page=page_0, **normalize_bbox(box, w, h))
        components = meta.get("confidenceComponents") or {}
        fields.append(
            FieldResult(
                name=name,
                type=_kind_of(value),
                value=value,
                page=page_0,
                confidence=components.get("groundingScore"),
                match=meta.get("match"),
                citation=citation,
            )
        )
    return StructuredData(fields=fields, extraction=extraction)


def _build_code(filename: str, echo: dict, *, include_confidence: bool,
                include_source_locations: bool, schema: str = "") -> str:
    """The snippet the UI shows as 'how you'd do this yourself'.

    `schema` is embedded so the snippet actually runs. It used to end with
    `request.schema = SCHEMA` against an undefined name, so "runnable as printed"
    held only if the reader noticed and supplied one — in a snippet whose whole
    purpose is being copied verbatim. Defaulted to "" so existing callers and
    tests that do not care about the schema keep working.
    """
    # The echo names the provider the USER chose; the SDK needs the one it accepts.
    # For Bedrock those differ, and printing "bedrock" would hand out a snippet
    # that cannot run.
    wire_provider = "openai" if echo["provider"] == "bedrock" else echo["provider"]
    bedrock_note = (
        "    # Bedrock speaks the OpenAI chat-completions API, so the provider is\n"
        '    # "openai" and the endpoint points at Bedrock. The trailing /v1 matters.\n'
        if echo["provider"] == "bedrock"
        else ""
    )
    endpoint_line = (
        f'    ai.endpoint = "{echo["endpoint"]}"\n' if "endpoint" in echo else ""
    )
    # Read from the environment, never print the value: this snippet is a
    # selling point prospects copy verbatim, and it must neither leak the
    # actual key nor suggest hardcoding one is fine. Looked up by the provider
    # the USER chose (echo["provider"]), not wire_provider — Bedrock's key is
    # BEDROCK_API_KEY even though the wire provider string is "openai".
    key_env = _API_KEY_ENV.get(echo["provider"])
    key_line = f'    ai.api_key = os.environ["{key_env}"]\n' if key_env else ""
    import_line = "import os\n" if key_env else ""
    # The outer {"schema": {...}} envelope the SDK requires is already part of
    # what the caller sent, so embedding it verbatim keeps the snippet correct.
    # A bare JSON Schema here would earn InvalidArgumentException 3016.
    # The snippet ALWAYS defines SCHEMA. It used to end with
    # `request.schema = SCHEMA` against a name nothing assigned, so a prospect
    # who copied it verbatim — the entire point of the snippet — got a
    # NameError. Callers that pass no schema get an honest placeholder rather
    # than a dangling reference.
    #
    # Triple-quoted for readability, since an escaped one-liner is noise in
    # something meant to be read. Valid JSON cannot contain three BARE quotes
    # (they arrive escaped as \\") so the else branch is effectively always
    # taken; the json.dumps fallback is belt-and-braces for a hand-built
    # schema that never passed through JSON.stringify.
    if not schema:
        schema_block = (
            'SCHEMA = \'{"schema": {"type": "object", "properties": {}}}\''
            "  # your schema, in the envelope the SDK requires\n\n"
        )
    elif '"""' in schema:
        schema_block = f"SCHEMA = {json.dumps(schema)}\n\n"
    else:
        schema_block = f'SCHEMA = """{schema}"""\n\n'
    return (
        import_line
        + "from nutrient_sdk import Document, StructuredExtractionRequest, Vision\n\n"
        + schema_block
        + f'with Document.open("{filename}") as document:\n'
        "    ai = document.settings.ai_processing_settings\n"
        + bedrock_note
        + f'    ai.provider = "{wire_provider}"\n'
        + key_line
        + endpoint_line
        + f'    ai.model = "{echo["model"]}"\n'
        + f"    ai.include_confidence = {include_confidence}\n"
        + f"    ai.include_source_locations = {include_source_locations}\n"
        + "    request = StructuredExtractionRequest()\n"
        + "    request.schema = SCHEMA\n"
        + "    result = Vision.set(document).extract_structured(request)\n"
    )


def extract_structured(
    file_bytes: bytes,
    original_filename: str,
    schema: str,
    *,
    instructions: str = "",
    provider: str = "openai",
    model: str | None = None,
    include_confidence: bool = True,
    include_source_locations: bool = True,
    include_page_images: bool = False,
    strict: bool = False,
) -> Envelope:
    from nutrient_sdk import Document, StructuredExtractionRequest, Vision

    # Reject a bad provider/model pair before touching the file: the alternative
    # is writing a temp file and letting the SDK open (and license-check) the
    # whole document only to raise anyway.
    validate_provider_and_model(provider, model)

    with _prepared_document(file_bytes, original_filename) as path:
        start = time.perf_counter()
        with Document.open(path) as document:
            ai = document.settings.ai_processing_settings
            echo = apply_provider(ai, provider, model=model)
            ai.include_confidence = include_confidence
            ai.include_source_locations = include_source_locations
            # 1.0.9+ only; absent on 1.0.8, where assigning it would be a no-op.
            ai.include_page_images = include_page_images
            ai.strict_structured_output = strict
            request = StructuredExtractionRequest()
            request.schema = schema
            request.instructions = instructions
            raw = Vision.set(document).extract_structured(request)
        timing_ms = int((time.perf_counter() - start) * 1000)

    return Envelope(
        feature="structured_extraction",
        resultType="structured",
        config=echo,
        timingMs=timing_ms,
        filename=original_filename,
        data=parse_structured(raw, original_filename).model_dump(),
        raw=raw,
        code=_build_code(
            original_filename,
            echo,
            include_confidence=include_confidence,
            include_source_locations=include_source_locations,
            schema=schema,
        ),
    )
