from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response

from app.services.editor import get_metadata

router = APIRouter(prefix="/api/editor")


@router.post("/metadata")
async def metadata(file: UploadFile = File(...)):
    try:
        data = await file.read()
        result = get_metadata(data)
        return Response(content=result, media_type="application/xml")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
