from pathlib import Path
import tempfile

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response

from app.services.signing import sign_with_demo_cert, sign_document, DEMO_CERT_PATH, DEMO_CERT_PASSWORD

router = APIRouter(prefix="/api/signing")


@router.get("/demo-certificate")
def get_demo_certificate():
    try:
        from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
        cert_bytes = DEMO_CERT_PATH.read_bytes()
        _, cert, _ = load_key_and_certificates(cert_bytes, DEMO_CERT_PASSWORD.encode())
        from cryptography.hazmat.primitives.serialization import Encoding
        der_bytes = cert.public_bytes(Encoding.DER)
        return Response(
            content=der_bytes,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "inline; filename=demo-certificate.der"},
        )
    except ImportError:
        # Fallback: return raw p12 if cryptography not installed
        return Response(
            content=DEMO_CERT_PATH.read_bytes(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": "inline; filename=demo-certificate.p12"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sign-demo")
async def sign_demo(file: UploadFile = File(...)):
    try:
        data = await file.read()
        result = sign_with_demo_cert(data)
        return Response(
            content=result,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=signed.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sign")
async def sign(
    file: UploadFile = File(...),
    certificate: UploadFile = File(...),
    password: str = Form(""),
):
    try:
        pdf_data = await file.read()
        cert_data = await certificate.read()
        result = sign_document(pdf_data, cert_data, password)
        return Response(
            content=result,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=signed.pdf"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
