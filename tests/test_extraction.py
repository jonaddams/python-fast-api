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


def test_ocr_endpoint_markdown_key_set_matches_json(
    client: TestClient, sample_image_bytes: bytes, sample_image_name: str
):
    # THE regression this guards: the markdown branch used to return only
    # [config, engine, filename, markdown, processedPages, timingMs,
    # totalPages], omitting statistics/textElements/fullText/pages/rawElements
    # entirely. The frontend's OcrResults reads those unconditionally, so a
    # markdown run blanked the whole results panel. Both branches must return
    # the same key set, with empty values on the markdown side.
    json_response = client.post(
        "/api/extraction/ocr",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
        data={"output_format": "json"},
    )
    markdown_response = client.post(
        "/api/extraction/ocr",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
        data={"output_format": "markdown"},
    )
    assert json_response.status_code == 200, json_response.text
    assert markdown_response.status_code == 200, markdown_response.text
    json_keys = set(json_response.json().keys())
    markdown_keys = set(markdown_response.json().keys())
    assert markdown_keys == json_keys

    markdown_body = markdown_response.json()
    assert markdown_body["engine"] == "OCR"
    assert markdown_body["statistics"] == {
        "totalElements": 0,
        "textElements": 0,
        "averageConfidence": 0,
        "lowConfidenceElements": 0,
    }
    assert markdown_body["textElements"] == []
    assert markdown_body["fullText"] == ""
    assert markdown_body["pages"] == []
    assert len(markdown_body["markdown"]) > 0


def test_ocr_endpoint_maps_unsupported_language_to_400(
    client: TestClient, sample_image_bytes: bytes, sample_image_name: str
):
    # Guards the exception-handler order in the /ocr route: UnsupportedOcrOption
    # must be caught before the generic Exception clause, or the allowlist's
    # whole point — a 400 naming the offending code — silently degrades to a
    # 500 with every other test still green. validate_ocr_options runs before
    # any Vision call, so this makes no API calls and stays fast.
    response = client.post(
        "/api/extraction/ocr",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
        data={"languages": "eng,deu"},
    )
    assert response.status_code == 400, response.text
    assert "eng,deu" in response.json()["detail"]


def test_icr_endpoint_returns_text(client: TestClient, sample_image_bytes: bytes, sample_image_name: str):
    response = client.post(
        "/api/extraction/icr",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "ICR"
    assert body["statistics"]["totalElements"] > 0


def test_icr_endpoint_returns_code_timing_and_config(
    client: TestClient, sample_image_bytes: bytes, sample_image_name: str
):
    resp = client.post(
        "/api/extraction/icr",
        files={"file": (sample_image_name, sample_image_bytes, "image/png")},
    )
    body = resp.json()
    assert isinstance(body["timingMs"], int)
    assert body["config"] == {"engine": "ICR"}
    assert "VisionEngine.ICR" in body["code"]


def test_icr_and_vlm_return_the_same_key_set(
    client: TestClient, sample_image_bytes: bytes, sample_image_name: str, monkeypatch
):
    # Not parity with /ocr: that endpoint also returns `markdown`, which neither
    # of these engines produces. Parity with EACH OTHER is what the studio's
    # single results component depends on.
    monkeypatch.setattr(
        "app.services.extraction._extract_with_engine",
        lambda *a, **k: {"engine": "STUB", "textElements": []},
    )
    from app.services.extraction import extract_text_icr, extract_text_vlm

    icr = extract_text_icr(b"", "s.pdf")
    vlm = extract_text_vlm(b"", "s.pdf", provider="claude")
    assert set(icr) == set(vlm)
    assert {"code", "timingMs", "config"} <= set(icr)


def test_vlm_config_names_the_provider_it_ran_with(monkeypatch):
    monkeypatch.setattr(
        "app.services.extraction._extract_with_engine",
        lambda *a, **k: {"engine": "STUB", "textElements": []},
    )
    from app.services.extraction import extract_text_vlm

    assert extract_text_vlm(b"", "s.pdf", provider="openai")["config"] == {
        "engine": "VLM",
        "provider": "openai",
    }


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
