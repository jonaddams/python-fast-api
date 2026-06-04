from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import requires_anthropic

USENIX_PDF = Path(__file__).resolve().parent / "fixtures" / "usenix-paper.pdf"


@requires_anthropic
def test_markdown_endpoint_returns_markdown(client: TestClient):
    response = client.post(
        "/api/extraction/markdown",
        files={"file": (USENIX_PDF.name, USENIX_PDF.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_MARKDOWN"
    assert body["provider"] == "claude"
    assert body["charCount"] > 0
    assert body["charCount"] == len(body["markdown"])
    assert "#" in body["markdown"]  # at least one heading
    assert body["totalPages"] >= 1
    assert body["processedPages"] >= 1
