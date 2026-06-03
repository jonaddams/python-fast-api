from fastapi.testclient import TestClient
from tests.conftest import requires_anthropic


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


def test_ocr_endpoint_extracts_image_only_pdf(client: TestClient):
    from pathlib import Path

    pdf_path = Path(__file__).resolve().parent / "fixtures" / "ocr-invoice.pdf"
    pdf_bytes = pdf_path.read_bytes()
    response = client.post(
        "/api/extraction/ocr",
        files={"file": (pdf_path.name, pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "OCR"
    assert body["statistics"]["totalElements"] > 0


def test_licensed_vision_features_is_full_set():
    # vision_form IS licensed on this key (guarded live by
    # tests/sdk/test_vision.py::test_form_feature_is_licensed), so the
    # stale FORM opt-out must be gone and the default feature set complete.
    from nutrient_sdk import VisionFeatures

    from app.services.extraction import _LICENSED_VISION_FEATURES

    assert _LICENSED_VISION_FEATURES == VisionFeatures.ALL.value


def test_prepared_input_renders_pdf_to_vlm_safe_jpeg(invoice_pdf_bytes: bytes):
    # export_as_image() writes TIFF bytes regardless of the output extension
    # (SDK-030). OpenAI's VLM API rejects TIFF with invalid_image_format, and
    # the SDK's internal re-encode of large renders can exceed Anthropic's
    # 10 MB request cap, so the pre-render must produce a compact JPEG.
    import os

    from app.services.extraction import _prepared_input

    with _prepared_input(invoice_pdf_bytes, "ocr-invoice.pdf") as path:
        with open(path, "rb") as f:
            magic = f.read(3)
        size = os.path.getsize(path)
    assert magic == b"\xff\xd8\xff", f"expected JPEG magic, got {magic!r}"
    # Stay well under the 10 MB VLM request cap even after base64 + SDK re-encode.
    assert size < 5_000_000, f"render unexpectedly large: {size} bytes"


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


@requires_anthropic
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


@requires_anthropic
def test_describe_endpoint_detailed_level(client: TestClient, sample_image_bytes: bytes, sample_image_name: str):
    response = client.post(
        "/api/extraction/describe",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
        data={"provider": "claude", "level": "detailed"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_DESCRIBE"
    assert body["level"] == "detailed"
    assert isinstance(body["text"], str) and len(body["text"]) > 0
