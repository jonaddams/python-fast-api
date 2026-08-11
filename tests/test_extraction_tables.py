from fastapi.testclient import TestClient

from tests.conftest import requires_anthropic, requires_openai, skip_if_openai_unavailable
from app.services.extraction import _format_tables


@requires_anthropic
def test_tables_endpoint_returns_structured_tables(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/tables",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_TABLES"
    assert body["provider"] == "claude"
    assert body["tableCount"] >= 1
    first = body["tables"][0]
    assert first["rowCount"] >= 1
    assert first["columnCount"] >= 1
    assert len(first["cells"]) >= 1
    cell = first["cells"][0]
    assert {"row", "column", "rowSpan", "colSpan", "text", "confidence", "bounds"} <= set(cell)
    assert body["totalPages"] >= 1
    assert body["processedPages"] >= 1


@requires_openai
def test_tables_endpoint_openai_provider_returns_same_shape(client: TestClient, invoice_pdf_bytes: bytes):
    response = client.post(
        "/api/extraction/tables?provider=openai",
        files={"file": ("ocr-invoice.pdf", invoice_pdf_bytes, "application/pdf")},
    )
    skip_if_openai_unavailable(response)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "VLM_TABLES"
    assert body["provider"] == "openai"
    assert "tables" in body and isinstance(body["tables"], list)


# --- Pure unit tests for _format_tables, below. No SDK, no network. ---
#
# Cell bounds come back from the SDK as ABSOLUTE raster pixels (measured
# 2026-08-11: up to 4345x5542 on a real document), while the studio's overlay
# consumes fractional 0..1 citations. Handing it raw bounds collapses every
# box into the page's top-left corner, which reads as a drawing bug rather
# than a units bug — hence these tests. Their names contain neither "live"
# nor "endpoint", so the pure-subset command's `-k "not live and not
# endpoint"` filter keeps them and drops the two live tests above.


def table(page_number=1, cells=None, **over):
    return {
        "type": "table",
        "pageNumber": page_number,
        "rowCount": 1,
        "columnCount": 1,
        "cells": cells if cells is not None else [],
        **over,
    }


def cell(**over):
    base = {
        "row": 0, "column": 0, "rowSpan": 1, "colSpan": 1,
        "text": "A", "confidence": 0.91, "bounds": None,
    }
    return {**base, **over}


PAGES = [{"page": 1, "width": 1000, "height": 2000}]


class TestFormatTables:
    def test_cell_citation_is_fractional(self):
        merged = {
            "elements": [table(cells=[cell(bounds={"x": 100, "y": 400, "width": 200, "height": 200})])],
            "pages": PAGES,
        }
        c = _format_tables(merged, "x.pdf", "claude")["tables"][0]["cells"][0]["citation"]
        assert c["x0"] == 0.1
        assert c["x1"] == 0.3
        assert c["y0"] == 0.2
        assert c["y1"] == 0.3
        # Raw bounds stay alongside, exactly as the OCR path keeps both.
        assert _format_tables(merged, "x.pdf", "claude")["tables"][0]["cells"][0]["bounds"]["x"] == 100

    def test_citation_page_is_zero_based(self):
        merged = {
            "elements": [table(page_number=3, cells=[cell(bounds={"x": 0, "y": 0, "width": 10, "height": 10})])],
            "pages": [{"page": 3, "width": 1000, "height": 2000}],
        }
        out = _format_tables(merged, "x.pdf", "claude")
        assert out["tables"][0]["cells"][0]["citation"]["page"] == 2
        assert out["tables"][0]["page"] == 2

    def test_citation_is_none_when_the_cell_has_no_bounds(self):
        merged = {"elements": [table(cells=[cell(bounds=None)])], "pages": PAGES}
        assert _format_tables(merged, "x.pdf", "claude")["tables"][0]["cells"][0]["citation"] is None

    def test_citation_is_none_when_the_page_has_no_dimensions(self):
        # Without raster dims a bbox cannot be normalised. Returning None is the
        # honest answer; guessing a scale would misplace every box.
        merged = {
            "elements": [table(cells=[cell(bounds={"x": 100, "y": 400, "width": 200, "height": 200})])],
            "pages": [],
        }
        assert _format_tables(merged, "x.pdf", "claude")["tables"][0]["cells"][0]["citation"] is None

    def test_page_is_none_when_the_element_has_no_page_number(self):
        merged = {"elements": [table(page_number=None, cells=[])], "pages": PAGES}
        assert _format_tables(merged, "x.pdf", "claude")["tables"][0]["page"] is None

    def test_pages_array_is_passed_through(self):
        merged = {"elements": [table(cells=[])], "pages": PAGES}
        assert _format_tables(merged, "x.pdf", "claude")["pages"] == PAGES

    def test_non_table_elements_are_filtered_but_kept_in_rawElements(self):
        merged = {
            "elements": [table(cells=[cell()]), {"type": "paragraph", "text": "not a table"}],
            "pages": PAGES,
        }
        out = _format_tables(merged, "x.pdf", "claude")
        assert out["tableCount"] == 1
        assert len(out["rawElements"]) == 2

    def test_confidence_is_rounded_and_none_becomes_zero(self):
        merged = {"elements": [table(cells=[cell(confidence=None)])], "pages": PAGES}
        assert _format_tables(merged, "x.pdf", "claude")["tables"][0]["cells"][0]["confidence"] == 0
