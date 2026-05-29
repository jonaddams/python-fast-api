from fastapi.testclient import TestClient


def test_ocr_endpoint_returns_text(client: TestClient, sample_image_bytes: bytes, sample_image_name: str):
    response = client.post(
        "/api/extraction/ocr",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "OCR"
    assert body["filename"] == sample_image_name
    assert body["statistics"]["totalElements"] > 0
    assert len(body["fullText"]) > 0


def test_icr_endpoint_returns_text(client: TestClient, sample_image_bytes: bytes, sample_image_name: str):
    response = client.post(
        "/api/extraction/icr",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "ICR"
    assert body["statistics"]["totalElements"] > 0


def test_vlm_endpoint_returns_503_when_local_vlm_unavailable(
    client: TestClient, sample_image_bytes: bytes, sample_image_name: str
):
    response = client.post(
        "/api/extraction/vlm",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
    )
    # Default Nutrient VLM_ENHANCED_ICR engine connects to localhost:1234.
    # When no local VLM server is running we expect a clear 503, not a generic 500.
    assert response.status_code == 503, response.text
    body = response.json()
    assert "localhost:1234" in body["detail"] or "VLM" in body["detail"]


def test_vlm_endpoint_with_claude_provider_returns_extraction(
    client: TestClient, sample_image_bytes: bytes, sample_image_name: str
):
    response = client.post(
        "/api/extraction/vlm?provider=claude",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM"
    assert body["statistics"]["totalElements"] > 0
    assert len(body["fullText"]) > 0


def test_describe_endpoint_returns_text(client: TestClient, sample_image_bytes: bytes, sample_image_name: str):
    response = client.post(
        "/api/extraction/describe",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
        data={"provider": "claude"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_DESCRIBE"
    assert body["provider"] == "claude"
    assert isinstance(body["text"], str) and len(body["text"]) > 0
