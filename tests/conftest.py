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
