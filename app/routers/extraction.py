from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query

from app.services.extraction import (
    extract_text_ocr,
    extract_text_icr,
    extract_text_vlm,
    describe_image,
    extract_tables,
    LocalVlmUnavailable,
)

router = APIRouter(prefix="/api/extraction")


@router.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    try:
        data = await file.read()
        return extract_text_ocr(data, file.filename or "input")
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
):
    try:
        data = await file.read()
        return describe_image(data, file.filename or "input", prompt=prompt, provider=provider)
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
