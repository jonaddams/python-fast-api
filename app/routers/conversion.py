from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response

from app.services.conversion import convert_to_pdf, pdf_to_html, pdf_to_docx, pdf_to_xlsx

router = APIRouter(prefix="/api/conversion")


@router.post("/docx-to-pdf")
async def docx_to_pdf(file: UploadFile = File(...)):
    return await _convert_to_pdf(file)


@router.post("/xlsx-to-pdf")
async def xlsx_to_pdf(file: UploadFile = File(...)):
    return await _convert_to_pdf(file)


@router.post("/pptx-to-pdf")
async def pptx_to_pdf(file: UploadFile = File(...)):
    return await _convert_to_pdf(file)


@router.post("/html-to-pdf")
async def html_to_pdf(file: UploadFile = File(...)):
    return await _convert_to_pdf(file)


@router.post("/md-to-pdf")
async def md_to_pdf(file: UploadFile = File(...)):
    return await _convert_to_pdf(file)


@router.post("/pdf-to-html")
async def convert_pdf_to_html(file: UploadFile = File(...)):
    try:
        data = await file.read()
        result = pdf_to_html(data)
        return Response(content=result, media_type="text/html")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pdf-to-docx")
async def convert_pdf_to_docx(file: UploadFile = File(...)):
    try:
        data = await file.read()
        result = pdf_to_docx(data)
        return Response(
            content=result,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment; filename=output.docx"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pdf-to-xlsx")
async def convert_pdf_to_xlsx(file: UploadFile = File(...)):
    try:
        data = await file.read()
        result = pdf_to_xlsx(data)
        return Response(
            content=result,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment; filename=output.xlsx"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _convert_to_pdf(file: UploadFile) -> Response:
    try:
        data = await file.read()
        result = convert_to_pdf(data, file.filename or "input")
        return Response(
            content=result,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=output.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
