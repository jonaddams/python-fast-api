import json

import pytest

from app.services.extraction import _format_extraction_result, merge_element_pages
from app.services.geometry import normalize_bbox


def test_converts_raster_pixels_to_fractional_coordinates():
    box = normalize_bbox({"x": 827, "y": 1169, "width": 827, "height": 1169}, 1654, 2338)
    assert box == {"x0": 0.5, "y0": 0.5, "x1": 1.0, "y1": 1.0}


def test_clamps_overflowing_boxes_into_range():
    # OCR bounds can exceed the raster by a pixel or two; a citation outside
    # 0..1 would place an annotation off the page rather than at its edge.
    box = normalize_bbox({"x": -10, "y": -10, "width": 5000, "height": 5000}, 100, 100)
    assert box == {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}


def test_rejects_non_positive_page_dimensions():
    # Dividing by a zero page dimension would yield inf/nan and paint nothing,
    # which is harder to diagnose than a raised error.
    with pytest.raises(ValueError):
        normalize_bbox({"x": 0, "y": 0, "width": 1, "height": 1}, 0, 100)


RAW_PAGE = json.dumps(
    {
        "metadata": [{"pageNumber": 1, "width": 1654, "height": 2338, "dpiX": 96, "dpiY": 96}],
        "elements": [
            {
                "type": "paragraph",
                "text": "Invoice",
                "readingOrder": 0,
                "pageNumber": 1,
                "confidence": 0.95,
                "bounds": {"x": 827, "y": 1169, "width": 827, "height": 1169},
                "words": [
                    {
                        "text": "Invoice",
                        "confidence": 0.9503,
                        "bounds": {"x": 827, "y": 1169, "width": 100, "height": 50},
                    }
                ],
            }
        ],
    }
)


def test_merge_preserves_page_dimensions():
    # Without this the OCR path has no way to normalise bounds, because each
    # per-page Vision call reports its own metadata and merge dropped it.
    merged = merge_element_pages([RAW_PAGE, RAW_PAGE])
    assert merged["pages"] == [
        {"page": 1, "width": 1654, "height": 2338},
        {"page": 2, "width": 1654, "height": 2338},
    ]
    assert len(merged["elements"]) == 2


def test_format_emits_a_fractional_citation_per_element():
    merged = merge_element_pages([RAW_PAGE])
    result = _format_extraction_result(merged, "scan.pdf", "ADAPTIVE_OCR")
    element = result["textElements"][0]
    assert element["page"] == 0  # 0-based, as the viewer expects
    assert element["citation"] == {"page": 0, "x0": 0.5, "y0": 0.5, "x1": 1.0, "y1": 1.0}
    assert result["pages"] == [{"page": 1, "width": 1654, "height": 2338}]


def test_format_tolerates_missing_page_dimensions():
    # A payload with no metadata must still return elements, just uncited —
    # dropping the text because geometry is unavailable would be worse.
    merged = {"elements": json.loads(RAW_PAGE)["elements"], "pages": []}
    result = _format_extraction_result(merged, "scan.pdf", "ADAPTIVE_OCR")
    assert result["textElements"][0]["citation"] is None
    assert result["textElements"][0]["text"] == "Invoice"
