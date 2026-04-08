from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response

from app.services.redaction import apply_redactions

router = APIRouter(prefix="/api/redaction")


@router.post("/apply")
async def redact(
    file: UploadFile = File(...),
    regions: str = Form(...),
):
    try:
        data = await file.read()
        result = apply_redactions(data, regions)
        return Response(
            content=result,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=redacted.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
