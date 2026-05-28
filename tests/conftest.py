from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_IMAGE = Path(__file__).resolve().parent / "fixtures" / "input_ocr_multiple_languages.png"


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_image_bytes() -> bytes:
    return SAMPLE_IMAGE.read_bytes()


@pytest.fixture
def sample_image_name() -> str:
    return SAMPLE_IMAGE.name
