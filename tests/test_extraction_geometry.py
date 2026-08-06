import pytest

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
