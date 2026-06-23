"""Pins the NAPY-20 / SDK-041 workaround.

On SDK 1.0.8 a narrow VisionFeatures selection (TABLE / KEY_VALUE_REGION alone)
fails extract_content() with the documentLayout/AiTextCorrection 3024 error, so the
tables and fields paths must request VisionFeatures.ALL and filter. These unit tests
capture the feature bitmask passed to the Vision call (no live VLM call) so a future
revert to a narrow feature fails loudly here instead of in production on 1.0.8.
"""

from nutrient_sdk import VisionFeatures

from app.services import extraction


def _capture_features(monkeypatch):
    captured = {}

    def fake_run(image_bytes, original_filename, engine, **kwargs):
        captured["features"] = kwargs.get("features")
        return {"elements": []}, 1, 1

    monkeypatch.setattr(extraction, "_run_with_prerender", fake_run)
    return captured


def test_extract_tables_requests_all_features(monkeypatch):
    captured = _capture_features(monkeypatch)
    extraction.extract_tables(b"%PDF-fake", "x.pdf", provider="claude")
    assert captured["features"] == VisionFeatures.ALL.value


def test_extract_fields_requests_all_features(monkeypatch):
    captured = _capture_features(monkeypatch)
    # The schema-driven describe() pass makes a live call; stub it out.
    monkeypatch.setattr(
        extraction, "_extract_schema_fields", lambda *a, **k: ({}, None)
    )
    extraction.extract_fields(b"%PDF-fake", "x.pdf", fields=["total"], provider="claude")
    assert captured["features"] == VisionFeatures.ALL.value
