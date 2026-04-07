from fastapi import APIRouter, UploadFile, File, HTTPException

from app.services.forms import list_form_fields

router = APIRouter(prefix="/api/forms")


@router.post("/list-fields")
async def list_fields(file: UploadFile = File(...)):
    try:
        data = await file.read()
        return list_form_fields(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
