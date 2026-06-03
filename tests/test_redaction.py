from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ACCOUNT_FORM = Path(__file__).resolve().parent / "fixtures" / "account-registration-form.pdf"


@pytest.fixture
def account_form_bytes() -> bytes:
    return ACCOUNT_FORM.read_bytes()


def test_redaction_apply_returns_redacted_pdf(client: TestClient, account_form_bytes: bytes):
    # The frontend sends 0-based page indices; the SDK's get_page() is 1-based.
    response = client.post(
        "/api/redaction/apply",
        files={"file": ("account-registration-form.pdf", account_form_bytes, "application/pdf")},
        data={"regions": '[{"page": 0, "x": 50, "y": 50, "width": 200, "height": 40}]'},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"
    # Applying a redaction must actually change the document.
    assert response.content != account_form_bytes
