"""Fork-safety spike + suite smoke test.

If these two tests pass under --forked but the corruption test poisons the
clean test when run WITHOUT --forked, that proves isolation is load-bearing
and correctly configured.
"""
import json
from pathlib import Path

import pytest
from nutrient_sdk import Document, Vision, VisionEngine, VisionFeatures

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
GOOD_PNG = FIXTURES / "input_ocr_multiple_languages.png"
SCANNED_PDF = FIXTURES / "ocr-invoice.pdf"
LICENSED_FEATURES = VisionFeatures.ALL.value - VisionFeatures.FORM.value


def _ocr(path: Path) -> list:
    with Document.open(str(path)) as doc:
        vs = doc.get_settings().get_vision_settings()
        vs.set_engine(VisionEngine.ADAPTIVE_OCR)
        vs.set_features(LICENSED_FEATURES)
        raw = Vision.set(doc).extract_content()
    return json.loads(raw)["elements"]


def test_smoke_ocr_on_png_succeeds():
    elements = _ocr(GOOD_PNG)
    assert len(elements) > 0


def test_fork_isolation_contains_vision_corruption():
    # This test triggers the known image-only-PDF Vision defect. Under --forked
    # it dies in its own child and CANNOT poison test_smoke_ocr_on_png_succeeds.
    with pytest.raises(Exception):
        _ocr(SCANNED_PDF)
