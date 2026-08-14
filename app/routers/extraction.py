import json

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query

from app.services.extraction import (
    extract_text_ocr,
    extract_text_icr,
    extract_text_vlm,
    describe_image,
    extract_tables,
    extract_markdown,
    extract_text_export,
    extract_fields,
    parse_field_names,
    LocalVlmUnavailable,
)
from app.services.ocr_options import UnsupportedOcrOption
from app.services.structured import (
    Envelope,
    ProviderNotConfigured,
    UnsupportedModel,
    available_providers,
    extract_structured,
)

router = APIRouter(prefix="/api/extraction")


@router.get("/providers")
async def providers():
    """Which providers this deployment can serve. The studio builds its dropdown
    from this so it never offers an option that would fail."""
    return {"providers": available_providers()}


@router.post("/ocr")
async def ocr(
    file: UploadFile = File(...),
    languages: str = Form(
        "eng",
        description="One or more codes joined with '+', e.g. 'eng' or 'eng+deu'. "
        "A comma or space makes the SDK return an EMPTY document, so anything "
        "outside the allowlist is rejected here with a 400.",
    ),
    table_detection: bool = Form(True, description="Detect tables as structured elements."),
    output_format: str = Form("json", description="'json' (elements) or 'markdown'."),
):
    try:
        data = await file.read()
        return extract_text_ocr(
            data,
            file.filename or "input",
            languages=languages,
            table_detection=table_detection,
            output_format=output_format,
        )
    except UnsupportedOcrOption as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/icr")
async def icr(file: UploadFile = File(...)):
    try:
        data = await file.read()
        return extract_text_icr(data, file.filename or "input")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vlm")
async def vlm(
    file: UploadFile = File(...),
    provider: str | None = Query(
        default=None,
        description="VLM provider override: 'claude' or 'openai'. If unset, uses the SDK's default (localhost:1234).",
    ),
):
    try:
        data = await file.read()
        return extract_text_vlm(data, file.filename or "input", provider=provider)
    except LocalVlmUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/describe")
async def describe(
    file: UploadFile = File(...),
    prompt: str | None = Form(None),
    provider: str = Form("claude"),
    level: str = Form("standard", description="Description level: 'standard' or 'detailed'."),
):
    try:
        data = await file.read()
        return describe_image(data, file.filename or "input", prompt=prompt, provider=provider, level=level)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tables")
async def tables(
    file: UploadFile = File(...),
    provider: str = Query("claude", description="VLM provider: 'claude' or 'openai'."),
):
    try:
        data = await file.read()
        return extract_tables(data, file.filename or "input", provider=provider)
    except LocalVlmUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/markdown")
async def markdown(
    file: UploadFile = File(...),
    provider: str = Query("claude", description="VLM provider: 'claude' or 'openai'."),
):
    try:
        data = await file.read()
        return extract_markdown(data, file.filename or "input", provider=provider)
    except LocalVlmUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/text")
async def text(file: UploadFile = File(...)):
    # No Query, no Form: export_as_text() takes no options, so there is nothing
    # to accept. No LocalVlmUnavailable branch either — no provider runs here.
    try:
        data = await file.read()
        return extract_text_export(data, file.filename or "input")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/structured", response_model=Envelope)
async def structured(
    file: UploadFile = File(...),
    json_schema: str = Form(
        ...,
        description='JSON schema envelope, e.g. {"schema": {"type": "object", '
        '"properties": {...}, "required": [...]}}.',
    ),
    instructions: str = Form("", description="Optional natural-language guidance."),
    provider: str = Query(
        "openai",
        description=(
            "Provider: 'openai', 'azure', 'anthropic' (alias 'claude'), 'bedrock' "
            "or 'local'. Anthropic requires the schema's object to set "
            "additionalProperties to false, or its API rejects the request with "
            "a 400. See GET /api/extraction/providers for which are configured "
            "on this deployment."
        ),
    ),
    model: str | None = Query(
        None,
        description=(
            "Optional model id. Only providers with a published model list accept "
            "this; see GET /api/extraction/providers. Rejected with 400 otherwise."
        ),
    ),
    includeConfidence: bool = Query(True),
    includeSourceLocations: bool = Query(
        True, description="Return source rectangles so each value can be located."
    ),
    includePageImages: bool = Query(
        False, description="Send page images alongside the parsed text (multimodal)."
    ),
    strict: bool = Query(
        False, description="Enforce the schema at the provider (structured output)."
    ),
):
    # Named `json_schema` on purpose. FastAPI synthesizes a body model from Form
    # parameters, so the parameter name becomes a field on that model — and
    # BOTH `schema` and `schema_json` shadow deprecated Pydantic v1 methods
    # still present on v2's BaseModel, each emitting a UserWarning at import.
    # `json_schema` does not (checked against dir(BaseModel)). Keeping `schema`
    # as the wire name via Field(alias=...) instead trips a FastAPI/Pydantic
    # compat bug that warns on every request — the worse trade.
    try:
        json.loads(json_schema)
    except ValueError as e:
        raise HTTPException(
            status_code=422, detail=f"json_schema is not valid JSON: {e}"
        )
    try:
        data = await file.read()
        return extract_structured(
            data,
            file.filename or "input",
            json_schema,
            instructions=instructions,
            provider=provider,
            model=model,
            include_confidence=includeConfidence,
            include_source_locations=includeSourceLocations,
            include_page_images=includePageImages,
            strict=strict,
        )
    # One clause: both are caller errors about the provider/model pair and both
    # map to the same 400 with the same detail. Two identical handlers invited
    # them to drift apart.
    except (UnsupportedModel, ProviderNotConfigured) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fields")
async def fields(
    file: UploadFile = File(...),
    fields: str = Form(..., description="Comma-separated list or JSON array of field names."),
    provider: str = Query("claude", description="VLM provider: 'claude' or 'openai'."),
):
    try:
        names = parse_field_names(fields)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not names:
        raise HTTPException(status_code=422, detail="fields must contain at least one field name")
    try:
        data = await file.read()
        return extract_fields(data, file.filename or "input", names, provider=provider)
    except LocalVlmUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
