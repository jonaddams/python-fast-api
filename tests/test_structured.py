"""Tests for schema-driven structured extraction.

The parsing, geometry and validation tests are pure — no SDK, no provider, no
cost. Only the two endpoint tests at the bottom make a live call, and they skip
when no key is configured.
"""

import json

import pytest

from app.services.structured import (
    Envelope,
    ProviderNotConfigured,
    UnsupportedModel,
    _kind_of,
    apply_provider,
    normalize_bbox,
    parse_structured,
)
from tests.conftest import (
    requires_openai,
    skip_if_openai_unavailable,
    skip_if_unlicensed,
)

SCHEMA = json.dumps(
    {
        "schema": {
            "type": "object",
            "properties": {
                "invoiceNumber": {
                    "type": "string",
                    "description": "The invoice number/reference",
                },
                "totalAmount": {
                    "type": "number",
                    "description": "The final total due, digits only",
                },
            },
            "required": ["invoiceNumber", "totalAmount"],
        }
    }
)


class TestNormalizeBbox:
    def test_normalize_xywh_to_fractional(self):
        # raster page 1650x2350 px; a real invoiceNumber bbox
        raw = {"x": 1402, "y": 219, "width": 163, "height": 19, "unit": "pt"}
        out = normalize_bbox(raw, page_w=1650, page_h=2350)
        assert out["x0"] == pytest.approx(1402 / 1650)
        assert out["y0"] == pytest.approx(219 / 2350)
        assert out["x1"] == pytest.approx((1402 + 163) / 1650)
        assert out["y1"] == pytest.approx((219 + 19) / 2350)

    def test_normalize_clamps_out_of_range(self):
        raw = {"x": -10, "y": 0, "width": 3000, "height": 4000}
        out = normalize_bbox(raw, page_w=1650, page_h=2350)
        assert out == {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}

    def test_nonpositive_page_dims_rejected(self):
        raw = {"x": 0, "y": 0, "width": 10, "height": 10}
        with pytest.raises(ValueError):
            normalize_bbox(raw, page_w=0, page_h=2350)


class TestKindOf:
    def test_bool_is_boolean_not_number(self):
        # bool is an int subclass in Python, so order of checks matters.
        assert _kind_of(True) == "boolean"

    @pytest.mark.parametrize(
        "value, expected",
        [(3, "number"), (3.5, "number"), ("x", "string"), (None, "string")],
    )
    def test_scalar_kinds(self, value, expected):
        assert _kind_of(value) == expected


class TestParseStructured:
    def test_builds_a_citation_in_fractional_page_coords(self):
        raw = json.dumps(
            {
                "extraction": {"invoiceNumber": "AC-2025-1047"},
                "metadata": {
                    "invoiceNumber": {
                        "page": 1,
                        "bbox": {"x": 825, "y": 235, "width": 165, "height": 20},
                        "match": "exact",
                        "confidenceComponents": {"groundingScore": 0.97},
                    }
                },
                "pages": [{"page": 1, "width": 1650, "height": 2350}],
            }
        )
        data = parse_structured(raw, "invoice.pdf")
        assert len(data.fields) == 1
        field = data.fields[0]
        assert field.name == "invoiceNumber"
        assert field.value == "AC-2025-1047"
        assert field.type == "string"
        assert field.confidence == pytest.approx(0.97)
        assert field.match == "exact"
        # page is reported 0-based for the viewer; the SDK reports 1-based.
        assert field.page == 0
        assert field.citation is not None
        assert field.citation.page == 0
        assert field.citation.x0 == pytest.approx(825 / 1650)

    def test_field_without_metadata_has_no_citation(self):
        raw = json.dumps(
            {"extraction": {"totalAmount": 1250.0}, "metadata": {}, "pages": []}
        )
        data = parse_structured(raw, "invoice.pdf")
        assert data.fields[0].citation is None
        assert data.fields[0].page is None
        assert data.fields[0].type == "number"

    def test_bbox_without_matching_page_dims_yields_no_citation(self):
        # A bbox referencing a page absent from pages[] cannot be normalized.
        raw = json.dumps(
            {
                "extraction": {"invoiceNumber": "X"},
                "metadata": {
                    "invoiceNumber": {
                        "page": 4,
                        "bbox": {"x": 1, "y": 1, "width": 1, "height": 1},
                    }
                },
                "pages": [{"page": 1, "width": 100, "height": 100}],
            }
        )
        data = parse_structured(raw, "invoice.pdf")
        assert data.fields[0].citation is None
        # The page number still survives, so the UI can say which page.
        assert data.fields[0].page == 3

    def test_null_value_is_preserved_as_a_field(self):
        # An optional field the document lacks must come back as a field with a
        # null value, not vanish — that distinction is the whole point of
        # marking schema fields optional.
        raw = json.dumps(
            {"extraction": {"netIncome": None}, "metadata": {}, "pages": []}
        )
        data = parse_structured(raw, "statement.pdf")
        assert [f.name for f in data.fields] == ["netIncome"]
        assert data.fields[0].value is None

    def test_extraction_dict_is_passed_through_verbatim(self):
        raw = json.dumps(
            {
                "extraction": {"a": 1, "b": "two", "c": False},
                "metadata": {},
                "pages": [],
            }
        )
        data = parse_structured(raw, "x.pdf")
        assert data.extraction == {"a": 1, "b": "two", "c": False}


class TestSchemaValidation:
    def test_malformed_json_schema_is_422(self, client, invoice_pdf_bytes):
        resp = client.post(
            "/api/extraction/structured",
            files={"file": ("invoice.pdf", invoice_pdf_bytes, "application/pdf")},
            data={"json_schema": "{not json"},
        )
        assert resp.status_code == 422
        assert "not valid JSON" in resp.json()["detail"]

    def test_missing_json_schema_is_422(self, client, invoice_pdf_bytes):
        resp = client.post(
            "/api/extraction/structured",
            files={"file": ("invoice.pdf", invoice_pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 422


class TestEndpoint:
    @requires_openai
    def test_structured_endpoint_returns_populated_envelope(
        self, client, invoice_pdf_bytes
    ):
        resp = client.post(
            "/api/extraction/structured",
            files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
            data={"json_schema": SCHEMA},
        )
        skip_if_unlicensed(resp)
        skip_if_openai_unavailable(resp)
        assert resp.status_code == 200, resp.text

        body = resp.json()
        # Shape is contractual — the studio UI reads every one of these.
        assert Envelope(**body)
        assert body["feature"] == "structured_extraction"
        assert body["resultType"] == "structured"
        assert body["filename"] == "ocr-invoice.pdf"
        assert body["timingMs"] > 0
        assert body["config"]["provider"] == "openai"
        assert "Vision.set(document).extract_structured" in body["code"]

        names = [f["name"] for f in body["data"]["fields"]]
        assert set(names) == {"invoiceNumber", "totalAmount"}

        # At least one field must come back with a real value — an all-null
        # result means the extraction did not work, not that the schema is fine.
        values = [f["value"] for f in body["data"]["fields"]]
        assert any(v not in (None, "") for v in values), body["data"]

    @requires_openai
    def test_citations_are_fractional_and_page_indexed(
        self, client, invoice_pdf_bytes
    ):
        resp = client.post(
            "/api/extraction/structured",
            files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
            data={"json_schema": SCHEMA},
        )
        skip_if_unlicensed(resp)
        skip_if_openai_unavailable(resp)
        assert resp.status_code == 200, resp.text

        cited = [f for f in resp.json()["data"]["fields"] if f.get("citation")]
        if not cited:
            pytest.skip("provider returned no source locations for this document")
        for field in cited:
            box = field["citation"]
            assert box["page"] >= 0
            for key in ("x0", "y0", "x1", "y1"):
                assert 0.0 <= box[key] <= 1.0, field
            assert box["x1"] >= box["x0"]
            assert box["y1"] >= box["y0"]


class _FakeAiSettings:
    """Stands in for ai_processing_settings. apply_provider only ever assigns
    attributes, so a bare object records exactly what it set."""

    def __init__(self):
        self.provider = None
        self.model = None
        self.api_key = None
        self.endpoint = None


class TestApplyProvider:
    """Pure — apply_provider only assigns attributes and builds the echo dict."""

    def test_anthropic_sets_a_model_and_the_anthropic_key(self, monkeypatch):
        # The flat ai.provider path has NO default model, unlike
        # ClaudeApiSettings. Omitting it fails with "AiProcessing model is
        # required", which reads as though the provider were unsupported.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "anthropic")
        assert ai.provider == "anthropic"
        assert ai.model, "anthropic must carry an explicit model"
        assert "claude" in ai.model
        assert ai.api_key == "test-anthropic-key"
        assert echo == {"provider": "anthropic", "model": ai.model}

    def test_claude_is_an_alias_for_anthropic(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "claude")
        # Normalised, so the echo names one provider however it was requested.
        assert ai.provider == "anthropic"
        assert echo["provider"] == "anthropic"

    def test_anthropic_leaves_the_endpoint_unset(self, monkeypatch):
        # The SDK defaults to https://api.anthropic.com/v1/; setting it here
        # would hardcode something that is already correct and may change.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "anthropic")
        assert ai.endpoint is None
        assert "endpoint" not in echo

    def test_anthropic_model_is_overridable(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr(
            "app.services.structured._DEFAULT_MODELS",
            {**__import__("app.services.structured", fromlist=["x"])._DEFAULT_MODELS,
             "anthropic": "claude-opus-5"},
        )
        ai = _FakeAiSettings()
        assert apply_provider(ai, "anthropic")["model"] == "claude-opus-5"

    def test_provider_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        ai = _FakeAiSettings()
        assert apply_provider(ai, "Claude")["provider"] == "anthropic"

    def test_openai_still_gets_its_own_key_and_no_endpoint(self, monkeypatch):
        # Regression guard: adding the anthropic branch must not disturb openai.
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "openai")
        assert ai.provider == "openai"
        assert ai.api_key == "test-openai-key"
        assert ai.endpoint is None
        assert "endpoint" not in echo

    def test_local_still_sets_an_endpoint(self, monkeypatch):
        monkeypatch.delenv("LM_STUDIO_API_URL", raising=False)
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "local")
        assert ai.endpoint == "http://localhost:1234/v1"
        assert echo["endpoint"] == "http://localhost:1234/v1"

    def test_unknown_provider_still_falls_back(self):
        # Documented existing behaviour, asserted so a change is deliberate:
        # an unrecognised provider gets the fallback model and no credentials.
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "gemini")
        assert echo["provider"] == "gemini"
        assert echo["model"] == "gpt-5.4"

    def test_bedrock_uses_the_openai_provider_string(self, monkeypatch):
        # The SDK rejects every provider value but "openai" on this path — verified
        # 2026-08-05: "azure" errors with "Use 'openai' (optionally with an
        # OpenAI-compatible endpoint)". So the wire provider is openai while the
        # echo still names bedrock, which is what the user chose.
        monkeypatch.setenv("BEDROCK_API_KEY", "test-bedrock-key")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "bedrock")
        assert ai.provider == "openai"
        assert echo["provider"] == "bedrock"

    def test_bedrock_endpoint_ends_in_v1(self, monkeypatch):
        # The SDK appends "/chat/completions" verbatim. Without the /v1 suffix the
        # request goes to /chat/completions and 404s.
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "bedrock")
        assert ai.endpoint == "https://bedrock-mantle.eu-west-1.api.aws/v1"
        assert echo["endpoint"] == ai.endpoint

    def test_bedrock_endpoint_is_overridable(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        monkeypatch.setenv("BEDROCK_ENDPOINT", "https://example.invalid/v1")
        ai = _FakeAiSettings()
        assert apply_provider(ai, "bedrock")["endpoint"] == "https://example.invalid/v1"

    def test_bedrock_sends_the_bedrock_key(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_API_KEY", "test-bedrock-key")
        ai = _FakeAiSettings()
        apply_provider(ai, "bedrock")
        assert ai.api_key == "test-bedrock-key"

    def test_bedrock_region_defaults_to_us_east_1(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("BEDROCK_ENDPOINT", raising=False)
        ai = _FakeAiSettings()
        assert apply_provider(ai, "bedrock")["endpoint"] == (
            "https://bedrock-mantle.us-east-1.api.aws/v1"
        )

    def test_bedrock_carries_an_explicit_model(self, monkeypatch):
        # Same trap as anthropic: the flat path has no default model, and omitting
        # it fails with "AiProcessing model is required". Asserting the concrete id
        # rather than truthiness, so removing the _DEFAULT_MODELS entry fails here —
        # `assert ai.model` alone passes for every provider via the fallback.
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "bedrock")
        assert ai.model == "qwen.qwen3-vl-235b-a22b"
        assert echo["model"] == "qwen.qwen3-vl-235b-a22b"


class TestModelAllowlist:
    """A configurable endpoint plus a free-form model would make /structured a
    general-purpose proxy. The allowlist is what stops that, and it also stops a
    typo'd model silently running a different one."""

    def test_an_allowed_model_is_used(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "bedrock", model="amazon.nova-pro-v1:0")
        assert ai.model == "amazon.nova-pro-v1:0"
        assert echo["model"] == "amazon.nova-pro-v1:0"

    def test_omitting_the_model_uses_the_env_default(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        ai = _FakeAiSettings()
        echo = apply_provider(ai, "bedrock", model=None)
        assert echo["model"] == "qwen.qwen3-vl-235b-a22b"

    def test_a_model_outside_the_allowlist_is_rejected(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        ai = _FakeAiSettings()
        with pytest.raises(UnsupportedModel) as exc:
            apply_provider(ai, "bedrock", model="anthropic.claude-sonnet-4-6")
        # The message must name what IS allowed; "invalid model" alone sends the
        # reader to the wrong place.
        assert "qwen.qwen3-vl-235b-a22b" in str(exc.value)

    def test_a_model_on_a_provider_without_an_allowlist_is_rejected(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        ai = _FakeAiSettings()
        with pytest.raises(UnsupportedModel) as exc:
            apply_provider(ai, "openai", model="gpt-4o")
        assert "openai" in str(exc.value)

    def test_omitting_the_model_on_openai_still_works(self, monkeypatch):
        # Regression guard: existing providers must be untouched.
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        ai = _FakeAiSettings()
        assert apply_provider(ai, "openai")["model"] == "gpt-5.4"


class TestModelEndpoint:
    def test_an_unsupported_model_returns_400_naming_the_alternatives(
        self, client, invoice_pdf_bytes
    ):
        response = client.post(
            "/api/extraction/structured",
            params={"provider": "bedrock", "model": "not-a-real-model"},
            files={"file": ("invoice.pdf", invoice_pdf_bytes, "application/pdf")},
            data={"json_schema": SCHEMA, "instructions": ""},
        )
        assert response.status_code == 400
        assert "qwen.qwen3-vl-235b-a22b" in response.json()["detail"]

    def test_rejection_happens_before_the_document_is_opened(self, client):
        # Deliberately invalid PDF bytes. If validation ran after Document.open(),
        # this would fail with a parse/license error rather than a clean 400 —
        # proving the model check happens before any SDK document work.
        response = client.post(
            "/api/extraction/structured",
            params={"provider": "bedrock", "model": "not-a-real-model"},
            files={"file": ("invoice.pdf", b"not a pdf", "application/pdf")},
            data={"json_schema": SCHEMA, "instructions": ""},
        )
        assert response.status_code == 400
        assert "qwen.qwen3-vl-235b-a22b" in response.json()["detail"]


class TestProviderNotConfigured:
    def test_bedrock_without_a_key_is_refused_locally(self, monkeypatch):
        # Better to fail here than to send "Bearer no-key" to AWS and surface a
        # token-parsing error that points nowhere useful.
        monkeypatch.delenv("BEDROCK_API_KEY", raising=False)
        ai = _FakeAiSettings()
        with pytest.raises(ProviderNotConfigured) as exc:
            apply_provider(ai, "bedrock")
        assert "BEDROCK_API_KEY" in str(exc.value)

    def test_a_configured_bedrock_is_fine(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        ai = _FakeAiSettings()
        assert apply_provider(ai, "bedrock")["provider"] == "bedrock"

    def test_endpoint_returns_400_when_bedrock_is_unconfigured(
        self, client, monkeypatch, invoice_pdf_bytes
    ):
        monkeypatch.delenv("BEDROCK_API_KEY", raising=False)
        response = client.post(
            "/api/extraction/structured",
            params={"provider": "bedrock"},
            files={"file": ("invoice.pdf", invoice_pdf_bytes, "application/pdf")},
            data={"json_schema": SCHEMA, "instructions": ""},
        )
        assert response.status_code == 400
        assert "BEDROCK_API_KEY" in response.json()["detail"]


class TestBuildCode:
    def test_bedrock_snippet_uses_openai_and_shows_the_endpoint(self):
        from app.services.structured import _build_code

        code = _build_code(
            "invoice.pdf",
            {
                "provider": "bedrock",
                "model": "qwen.qwen3-vl-235b-a22b",
                "endpoint": "https://bedrock-mantle.us-east-1.api.aws/v1",
            },
            include_confidence=True,
            include_source_locations=True,
        )
        # "bedrock" is not a value the SDK accepts; a copied snippet must run.
        assert 'ai.provider = "openai"' in code
        assert 'ai.provider = "bedrock"' not in code
        assert 'ai.endpoint = "https://bedrock-mantle.us-east-1.api.aws/v1"' in code
        assert "Bedrock speaks the OpenAI chat-completions API" in code

    def test_openai_snippet_has_no_endpoint_line(self):
        from app.services.structured import _build_code

        code = _build_code(
            "invoice.pdf",
            {"provider": "openai", "model": "gpt-5.4"},
            include_confidence=True,
            include_source_locations=True,
        )
        assert 'ai.provider = "openai"' in code
        assert "ai.endpoint" not in code


class TestAvailableProviders:
    """Availability is env-var presence only — no network probing. A reachability
    check would add per-request latency and would report Local as up whenever any
    process happened to hold port 1234."""

    def _ids(self, monkeypatch, **env):
        for name in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "BEDROCK_API_KEY",
            "LM_STUDIO_API_URL",
        ):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        from app.services.structured import available_providers

        return [p["id"] for p in available_providers()]

    def test_a_provider_without_its_key_is_absent(self, monkeypatch):
        assert self._ids(monkeypatch) == []

    def test_openai_appears_when_its_key_is_set(self, monkeypatch):
        assert self._ids(monkeypatch, OPENAI_API_KEY="k") == ["openai"]

    def test_bedrock_appears_when_its_key_is_set(self, monkeypatch):
        assert "bedrock" in self._ids(monkeypatch, BEDROCK_API_KEY="k")

    def test_local_is_gated_on_lm_studio_api_url(self, monkeypatch):
        # This is the mechanism that hides Local on Railway: the var is set in the
        # laptop .env and never in Railway.
        assert "local" not in self._ids(monkeypatch, OPENAI_API_KEY="k")
        assert "local" in self._ids(
            monkeypatch, LM_STUDIO_API_URL="http://localhost:1234/v1"
        )

    def test_bedrock_publishes_its_models_with_labels(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        from app.services.structured import available_providers

        bedrock = next(p for p in available_providers() if p["id"] == "bedrock")
        ids = {m["id"] for m in bedrock["models"]}
        assert ids == {"qwen.qwen3-vl-235b-a22b", "amazon.nova-pro-v1:0"}
        labels = {m["label"] for m in bedrock["models"]}
        assert "Qwen3-VL 235B" in labels
        # The models are not multimodal on this path — no image ever reaches the
        # wire — so no label may imply vision.
        assert not any("vision" in label.lower() for label in labels)

    def test_single_model_providers_publish_an_empty_model_list(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        from app.services.structured import available_providers

        openai = next(p for p in available_providers() if p["id"] == "openai")
        assert openai["models"] == []
        assert openai["defaultModel"] == "gpt-5.4"


class TestProvidersEndpoint:
    def test_it_returns_the_provider_list(self, client, monkeypatch):
        monkeypatch.setenv("BEDROCK_API_KEY", "k")
        response = client.get("/api/extraction/providers")
        assert response.status_code == 200
        ids = [p["id"] for p in response.json()["providers"]]
        assert "bedrock" in ids
