import base64
from pathlib import Path

from fastapi.testclient import TestClient

SAMPLE_PDF = Path(__file__).resolve().parent / "fixtures" / "input_forms_detection.pdf"


def test_detect_endpoint_adds_form_fields(client: TestClient):
    pdf_bytes = SAMPLE_PDF.read_bytes()
    response = client.post(
        "/api/forms/detect",
        files={"file": (SAMPLE_PDF.name, pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["inputFieldCount"] == 0
    assert body["detectedFieldCount"] > 0
    assert len(body["addedFields"]) == body["detectedFieldCount"]

    for field in body["addedFields"]:
        assert isinstance(field["name"], str) and field["name"]
        assert isinstance(field["type"], str) and field["type"].startswith("Pdf")

    decoded = base64.b64decode(body["pdfBase64"])
    assert decoded[:5] == b"%PDF-"
    assert len(decoded) > len(pdf_bytes)
