from fastapi.testclient import TestClient

from tests.conftest import requires_anthropic


@requires_anthropic
def test_fields_endpoint_extracts_requested_schema_fields(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/fields",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
        data={"fields": "invoice_number, total, billing_date"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_FIELDS"
    assert body["provider"] == "claude"
    assert body["requestedFields"] == ["invoice_number", "total", "billing_date"]
    # Schema path returns either a parsed object with the requested keys, or a parseError.
    if "parseError" not in body:
        assert set(body["schemaFields"].keys()) == {"invoice_number", "total", "billing_date"}
    # Native KEY_VALUE_REGION path must return without error (may be empty if the
    # feature is a no-op on this doc — that is itself a finding, see plan risk #1).
    assert isinstance(body["nativeRegions"], list)


@requires_anthropic
def test_fields_endpoint_accepts_json_array_fields(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/fields",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
        data={"fields": '["invoice_number", "total"]'},
    )
    assert response.status_code == 200, response.text
    assert response.json()["requestedFields"] == ["invoice_number", "total"]


def test_fields_endpoint_rejects_empty_fields(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/fields",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
        data={"fields": ""},
    )
    assert response.status_code == 422, response.text


def test_fields_endpoint_rejects_malformed_json_array(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/fields",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
        data={"fields": "[invoice_number, total]"},  # unquoted -> invalid JSON
    )
    assert response.status_code == 422, response.text
