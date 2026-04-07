import tempfile
import os
from pathlib import Path

from nutrient_sdk import PdfSigner, DigitalSignatureOptions

DEMO_CERT_PATH = Path(__file__).resolve().parent.parent / "certs" / "demo-certificate.p12"
DEMO_CERT_PASSWORD = "nutrient-demo"


def sign_with_demo_cert(pdf_bytes: bytes) -> bytes:
    if not DEMO_CERT_PATH.exists():
        raise FileNotFoundError(f"Demo certificate not found: {DEMO_CERT_PATH}")
    cert_bytes = DEMO_CERT_PATH.read_bytes()
    return sign_document(pdf_bytes, cert_bytes, DEMO_CERT_PASSWORD)


def sign_document(pdf_bytes: bytes, cert_bytes: bytes, password: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out, \
         tempfile.NamedTemporaryFile(suffix=".p12", delete=False) as cert:
        inp.write(pdf_bytes)
        cert.write(cert_bytes)
        inp_path, out_path, cert_path = inp.name, out.name, cert.name

    try:
        options = DigitalSignatureOptions()
        options.set_certificate_path(cert_path)
        options.set_certificate_password(password)
        options.set_signer_name("Nutrient SDK Demo")
        options.set_reason("Document signing demo")
        options.set_location("Nutrient Python SDK")

        with PdfSigner() as signer:
            signer.sign(inp_path, out_path, options)

        with open(out_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(inp_path)
        os.unlink(out_path)
        os.unlink(cert_path)
