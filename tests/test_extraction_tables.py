from fastapi.testclient import TestClient

from tests.conftest import requires_anthropic


@requires_anthropic
def test_tables_endpoint_returns_structured_tables(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/tables",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_TABLES"
    assert body["provider"] == "claude"
    assert body["tableCount"] >= 1
    first = body["tables"][0]
    assert first["rowCount"] >= 1
    assert first["columnCount"] >= 1
    assert len(first["cells"]) >= 1
    cell = first["cells"][0]
    assert {"row", "column", "rowSpan", "colSpan", "text", "confidence", "bounds"} <= set(cell)
