from pathlib import Path

from fastapi.testclient import TestClient


def _make_minimal_pdf() -> bytes:
    # Minimal valid PDF (1 page, no content) so we don't depend on a sample PDF in repo.
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000052 00000 n \n"
        b"0000000099 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF\n"
    )


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
