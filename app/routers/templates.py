from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response

from app.services.templates import generate_from_template

router = APIRouter(prefix="/api/templates")


@router.post("/generate")
async def generate(
    template: UploadFile = File(...),
    model: str = Form(...),
):
    try:
        template_bytes = await template.read()
        result = generate_from_template(
            template_bytes,
            template.filename or "template.docx",
            model,
        )
        return Response(
            content=result,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=output.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
