import json
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, Vision, VisionEngine, VisionFeatures

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect, fork_crash
from tests.sdk.conftest import requires_anthropic

LICENSED = VisionFeatures.ALL.value - VisionFeatures.FORM.value


def _extract(path, engine):
    with Document.open(path) as doc:
        vs = doc.get_settings().get_vision_settings()
        vs.set_engine(engine)
        vs.set_features(LICENSED)
        return json.loads(Vision.set(doc).extract_content())["elements"]


class TestBaseline:
    def test_ocr_on_png(self, ocr_png):
        assert len(_extract(ocr_png, VisionEngine.ADAPTIVE_OCR)) > 0

    def test_icr_on_png(self, ocr_png):
        assert len(_extract(ocr_png, VisionEngine.ICR)) > 0


class TestEdgeCases:
    @defect("SDK-026", "image-only/scanned PDF fails Vision at the InputImage stage")
    def test_scanned_pdf_extracts_or_raises_clean(self, scanned_pdf):
        # A clean SDK either rasterizes internally or raises a CLEAR typed error.
        # Today it raises a truncated VisionException. Assert success; expect xfail.
        assert len(_extract(scanned_pdf, VisionEngine.ADAPTIVE_OCR)) > 0

    def test_vision_set_none_is_typed(self):
        with pytest.raises(nutrient_sdk.NutrientException):
            Vision.set(None)

    @defect("SDK-027", "out-of-range feature bitmask not rejected")
    def test_bad_features_bitmask_rejected(self, ocr_png):
        with Document.open(ocr_png) as doc:
            vs = doc.get_settings().get_vision_settings()
            vs.set_engine(VisionEngine.ADAPTIVE_OCR)
            vs.set_features(999)
            with pytest.raises(nutrient_sdk.NutrientException):
                Vision.set(doc).extract_content()

    def test_form_feature_is_licensed(self, ocr_png):
        # vision_form IS licensed on this key, so requesting FORM must succeed.
        # (Guards the entitlement live; app/services/extraction.py uses the full
        # feature set since the SDK-028 cleanup. See DEFECTS.md SDK-028 note.)
        with Document.open(ocr_png) as doc:
            vs = doc.get_settings().get_vision_settings()
            vs.set_engine(VisionEngine.ADAPTIVE_OCR)
            vs.set_features(VisionFeatures.FORM.value)
            elements = json.loads(Vision.set(doc).extract_content())["elements"]
            assert len(elements) > 0


class TestSequential:
    @defect("SDK-003", "a failed Vision call poisons subsequent good calls in the same process")
    def test_failed_vision_does_not_poison_next(self, scanned_pdf, ocr_png):
        try:
            _extract(scanned_pdf, VisionEngine.ADAPTIVE_OCR)  # known to fail
        except Exception:
            pass
        # In a fresh process this PNG succeeds. After the failure above it
        # currently fails too (corruption). Assert the SAFE behavior.
        assert len(_extract(ocr_png, VisionEngine.ADAPTIVE_OCR)) > 0

    def test_repeated_ocr_no_segfault(self, ocr_png):
        for _ in range(25):
            assert len(_extract(ocr_png, VisionEngine.ADAPTIVE_OCR)) > 0


class TestDescribe:
    @fork_crash
    @requires_anthropic
    @defect("SDK-035", "Vision.describe() with a VLM provider (CLAUDE) crashes with SIGSEGV in a forked child process (fork-safety: same root as SDK-034)")
    def test_describe_returns_text(self, ocr_png):
        import os
        from nutrient_sdk.vlmprovider import VlmProvider
        with Document.open(ocr_png) as doc:
            s = doc.get_settings()
            s.get_vision_settings().set_provider(VlmProvider.CLAUDE)
            s.get_claude_api_settings().set_api_key(os.environ["ANTHROPIC_API_KEY"])
            text = Vision.set(doc).describe()
        assert isinstance(text, str) and len(text) > 0
