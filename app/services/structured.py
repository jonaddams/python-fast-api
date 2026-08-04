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
}
_FALLBACK_MODEL = "gpt-5.4"

# "claude" is the documented alias for "anthropic" on ai.provider. Normalising
# means callers can send either and the config echo still names one thing.
_PROVIDER_ALIASES = {"claude": "anthropic"}


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


def apply_provider(ai, provider: str) -> dict:
    """Point ai_processing_settings at the chosen provider; return a config echo."""
    provider = _PROVIDER_ALIASES.get(provider.lower(), provider.lower())
    model = _DEFAULT_MODELS.get(provider, _FALLBACK_MODEL)
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
    elif provider == "local":
        ai.endpoint = os.environ.get("LM_STUDIO_API_URL", "http://localhost:1234/v1")
        echo["endpoint"] = ai.endpoint
    return echo


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
                include_source_locations: bool) -> str:
    """The snippet the UI shows as 'how you'd do this yourself'."""
    return (
        "from nutrient_sdk import Document, StructuredExtractionRequest, Vision\n\n"
        f'with Document.open("{filename}") as document:\n'
        "    ai = document.settings.ai_processing_settings\n"
        f'    ai.provider = "{echo["provider"]}"\n'
        f'    ai.model = "{echo["model"]}"\n'
        f"    ai.include_confidence = {include_confidence}\n"
        f"    ai.include_source_locations = {include_source_locations}\n"
        "    request = StructuredExtractionRequest()\n"
        "    request.schema = SCHEMA\n"
        "    result = Vision.set(document).extract_structured(request)\n"
    )


def extract_structured(
    file_bytes: bytes,
    original_filename: str,
    schema: str,
    *,
    instructions: str = "",
    provider: str = "openai",
    include_confidence: bool = True,
    include_source_locations: bool = True,
    include_page_images: bool = False,
    strict: bool = False,
) -> Envelope:
    from nutrient_sdk import Document, StructuredExtractionRequest, Vision

    with _prepared_document(file_bytes, original_filename) as path:
        start = time.perf_counter()
        with Document.open(path) as document:
            ai = document.settings.ai_processing_settings
            echo = apply_provider(ai, provider)
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
        ),
    )
