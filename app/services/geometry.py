"""Bounding-box conversion shared by the structured and OCR extraction paths.

Lived in structured.py until 2026-08-06. OCR needs the identical conversion to
produce citations the studio's existing overlay can draw, and importing it from
structured.py would make the OCR path depend on an unrelated service.
"""


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def normalize_bbox(raw: dict, page_w: float, page_h: float) -> dict:
    """Convert a raw SDK bbox {x, y, width, height} (raster pixels, origin
    top-left; the 'unit' field is unreliable and ignored) to fractional page
    coords in 0..1, where page_w/page_h are the raster px dims for that page."""
    if page_w <= 0 or page_h <= 0:
        raise ValueError("page dimensions must be positive")
    x, y = float(raw["x"]), float(raw["y"])
    right, bottom = x + float(raw["width"]), y + float(raw["height"])
    return {
        "x0": _clamp01(x / page_w),
        "y0": _clamp01(y / page_h),
        "x1": _clamp01(right / page_w),
        "y1": _clamp01(bottom / page_h),
    }
