"""Per-forked-child SDK setup + shared fixtures for the defect-hunting suite."""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

load_dotenv(PROJECT_ROOT / ".env")


@pytest.fixture(autouse=True)
def _register_license():
    """Each forked child is a fresh process and must register the license."""
    from nutrient_sdk import License
    key = os.environ.get("NUTRIENT_LICENSE_KEY")
    if not key:
        pytest.skip("NUTRIENT_LICENSE_KEY not set")
    License.register_key(key)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def account_form(fixtures_dir) -> str:
    return str(fixtures_dir / "account-registration-form.pdf")


@pytest.fixture
def detection_pdf(fixtures_dir) -> str:
    return str(fixtures_dir / "input_forms_detection.pdf")


@pytest.fixture
def ocr_png(fixtures_dir) -> str:
    return str(fixtures_dir / "input_ocr_multiple_languages.png")


@pytest.fixture
def scanned_pdf(fixtures_dir) -> str:
    return str(fixtures_dir / "ocr-invoice.pdf")


requires_anthropic = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
requires_openai = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"
)
