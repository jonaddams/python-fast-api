"""Tests for the shared-secret gate.

Pure — no SDK, no provider, no cost. The middleware reads
EXTRACTION_SERVICE_TOKEN at request time, so monkeypatching the environment is
enough; no reimport or app rebuild is needed.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

TOKEN = "s3cr3t-token-value"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setenv("EXTRACTION_SERVICE_TOKEN", TOKEN)


@pytest.fixture
def open_service(monkeypatch):
    monkeypatch.delenv("EXTRACTION_SERVICE_TOKEN", raising=False)


class TestTokenConfigured:
    def test_correct_token_is_accepted(self, client, locked):
        res = client.get("/api/health", headers={"authorization": f"Bearer {TOKEN}"})
        assert res.status_code == 200

    def test_missing_header_is_rejected(self, client, locked):
        res = client.post("/api/extraction/structured")
        assert res.status_code == 401
        assert res.json() == {"detail": "Unauthorized"}

    def test_wrong_token_is_rejected(self, client, locked):
        res = client.post(
            "/api/extraction/structured",
            headers={"authorization": "Bearer not-the-token"},
        )
        assert res.status_code == 401

    def test_a_token_that_is_a_prefix_of_the_real_one_is_rejected(self, client, locked):
        # compare_digest, not startswith.
        res = client.post(
            "/api/extraction/structured",
            headers={"authorization": f"Bearer {TOKEN[:-1]}"},
        )
        assert res.status_code == 401

    @pytest.mark.parametrize(
        "header",
        [
            TOKEN,                    # bare, no scheme
            f"Basic {TOKEN}",         # wrong scheme
            "Bearer",                 # scheme, no credentials
            "Bearer ",                # scheme, empty credentials
            "",                       # present but empty
        ],
    )
    def test_malformed_authorization_headers_are_rejected(self, client, locked, header):
        res = client.post(
            "/api/extraction/structured", headers={"authorization": header}
        )
        assert res.status_code == 401

    def test_bearer_scheme_is_case_insensitive(self, client, locked):
        # RFC 7235 says the scheme is case-insensitive, and clients vary.
        res = client.get("/api/health", headers={"authorization": f"bearer {TOKEN}"})
        assert res.status_code == 200

    def test_health_is_reachable_without_a_token(self, client, locked):
        # The platform health check runs before any caller has a token, and the
        # response reveals nothing but liveness.
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_cors_preflight_is_not_rejected(self, client, locked):
        # A preflight carries no Authorization header by design. Rejecting it
        # would surface in the browser as an opaque CORS failure, not a 401.
        res = client.options(
            "/api/extraction/structured",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "POST",
            },
        )
        assert res.status_code != 401


class TestTokenNotConfigured:
    def test_service_is_open_when_no_token_is_set(self, client, open_service):
        # The browser-facing samples call this service directly, and a token
        # shipped to a browser is not a secret. Requiring one unconditionally
        # would break every one of them.
        res = client.get("/api/health")
        assert res.status_code == 200

    def test_a_stray_authorization_header_is_ignored_when_open(
        self, client, open_service
    ):
        res = client.get("/api/health", headers={"authorization": "Bearer whatever"})
        assert res.status_code == 200


class TestWarnIfOpen:
    def test_warns_when_no_token_is_configured(self, open_service, caplog):
        from app.auth import warn_if_open

        with caplog.at_level("WARNING"):
            warn_if_open()
        assert "EXTRACTION_SERVICE_TOKEN is not set" in caplog.text

    def test_silent_when_a_token_is_configured(self, locked, caplog):
        from app.auth import warn_if_open

        with caplog.at_level("WARNING"):
            warn_if_open()
        assert "EXTRACTION_SERVICE_TOKEN is not set" not in caplog.text
