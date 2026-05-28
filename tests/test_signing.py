from fastapi.testclient import TestClient
import pytest

from app.services.signing import DEMO_CERT_PATH

pytestmark = pytest.mark.skipif(
    not DEMO_CERT_PATH.exists(),
    reason=f"Demo certificate not found: {DEMO_CERT_PATH}",
)


def _make_minimal_pdf() -> bytes:
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Count 1/Kids[3 0 R]>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>",
    ]
    body = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(body))
        body += f"{i} 0 obj".encode() + obj + b"\nendobj\n"

    xref_offset = len(body)
    xref = b"xref\n0 4\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()
    xref += b"trailer<</Size 4/Root 1 0 R>>\n"
    xref += f"startxref\n{xref_offset}\n%%EOF\n".encode()
    return body + xref


def test_sign_demo_endpoint_returns_signed_pdf(client: TestClient):
    pdf_bytes = _make_minimal_pdf()
    response = client.post(
        "/api/signing/sign-demo",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    # Signed PDF should still be a valid PDF (starts with %PDF-) and longer than input
    # because a signature dict + cert data is appended.
    assert response.content[:5] == b"%PDF-"
    assert len(response.content) > len(pdf_bytes)
