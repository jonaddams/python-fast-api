import json
from pathlib import Path

from fastapi.testclient import TestClient

FORM_PDF = Path(__file__).resolve().parent / "fixtures" / "account-registration-form.pdf"


def test_list_fields_returns_form_metadata(client: TestClient):
    pdf_bytes = FORM_PDF.read_bytes()
    response = client.post(
        "/api/forms/list-fields",
        files={"file": (FORM_PDF.name, pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    fields = response.json()
    assert isinstance(fields, list) and len(fields) > 0

    for field in fields:
        assert isinstance(field["name"], str) and field["name"]
        assert isinstance(field["type"], str)
        assert isinstance(field["fieldType"], str)
        assert isinstance(field["widgetCount"], int)


def test_fill_fields_returns_filled_pdf(client: TestClient):
    pdf_bytes = FORM_PDF.read_bytes()
    values = json.dumps({"full_name": "Test User", "email": "test@example.com"})
    response = client.post(
        "/api/forms/fill-fields",
        files={"file": (FORM_PDF.name, pdf_bytes, "application/pdf")},
        data={"values": values},
    )
    assert response.status_code == 200, response.text
    assert response.content[:5] == b"%PDF-"
    assert len(response.content) > 0
