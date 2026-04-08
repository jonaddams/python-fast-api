from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response

from app.services.forms import list_form_fields, fill_form_fields

router = APIRouter(prefix="/api/forms")


@router.post("/list-fields")
async def list_fields(file: UploadFile = File(...)):
    try:
        data = await file.read()
        return list_form_fields(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fill-fields")
async def fill_fields(
    file: UploadFile = File(...),
    values: str = Form(...),
):
    try:
        data = await file.read()
        result = fill_form_fields(data, values)
        return Response(
            content=result,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=filled.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
