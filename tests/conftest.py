from pathlib import Path
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_IMAGE = Path(__file__).resolve().parent / "fixtures" / "input_ocr_multiple_languages.png"
OCR_INVOICE = Path(__file__).resolve().parent / "fixtures" / "ocr-invoice.pdf"

requires_anthropic = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
requires_openai = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_image_bytes() -> bytes:
    return SAMPLE_IMAGE.read_bytes()


@pytest.fixture
def sample_image_name() -> str:
    return SAMPLE_IMAGE.name


@pytest.fixture
def invoice_pdf_bytes() -> bytes:
    return OCR_INVOICE.read_bytes()


@pytest.fixture
def two_page_scanned_pdf(sample_image_bytes: bytes) -> bytes:
    """Image-only 2-page PDF built at test time from the committed PNG.

    Pillow writes raster-only PDF pages — exactly the input class that fails
    Vision without the pre-render (NAPY-8). No new binary is committed.
    """
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(sample_image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF", save_all=True, append_images=[img])
    return buf.getvalue()


def skip_if_openai_unavailable(response) -> None:
    """Skip a parity test when the OpenAI path is unavailable (invalid/expired
    key or unreachable endpoint) so the suite stays green until a valid
    OPENAI_API_KEY is configured. A genuine shape regression still fails the
    strict assertions that follow this call."""
    if response.status_code in (500, 503):
        detail = response.text.lower()
        signals = ("vlm endpoint", "properly configured", "401", "unauthorized",
                   "api key", "api_key", "api.openai.com")
        if any(s in detail for s in signals):
            pytest.skip(f"OpenAI path unavailable (refresh OPENAI_API_KEY): {response.text}")
