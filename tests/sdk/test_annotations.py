import tempfile

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor, Color

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


def _annots(editor):
    return editor.get_page_collection().get_page(1).get_annotation_collection()


class TestBaseline:
    def test_add_markup_and_roundtrip(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                annots = _annots(editor)
                before = annots.get_count()
                hl = annots.add_highlight(72.0, 700.0, 200.0, 20.0, "QA", "important")
                hl.set_color(Color.from_argb(255, 255, 255, 0))
                annots.add_sticky_note(300.0, 700.0, "QA", "Review", "verify")
                editor.save_as(out)
                editor.close()
            with Document.open(out) as doc:
                editor = PdfEditor.edit(doc)
                annots = _annots(editor)
                # each markup spawns a paired Popup -> +4 for 2 markups
                assert annots.get_count() == before + 4
                subtypes = [annots._get_item(i).get_sub_type()
                            for i in range(annots.get_count())]
                assert "Highlight" in subtypes
                assert "Text" in subtypes  # sticky note persists as /Text
                editor.close()
        finally:
            inputs.cleanup(out)


class TestEdgeCases:
    def test_page_index_zero_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                pages.get_page(0)  # 1-based API

    @defect("SDK-011", "get_rect() returns an opaque native handle int, not geometry")
    def test_get_rect_returns_readable_geometry(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(PdfEditor.edit(doc))
            a = annots.add_highlight(72.0, 700.0, 200.0, 20.0, "QA", "x")
            rect = a.get_rect()
            # A usable API returns something with numeric coordinates.
            assert hasattr(rect, "__iter__") or hasattr(rect, "x")

    @defect("SDK-024", "add_highlight accepts negative/zero geometry without validation")
    def test_negative_geometry_rejected(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(PdfEditor.edit(doc))
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                annots.add_highlight(72.0, 700.0, -200.0, 0.0, "QA", "x")

    @defect("SDK-024", "add_square accepts NaN/inf coordinates without validation")
    def test_non_finite_coords_rejected(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(PdfEditor.edit(doc))
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                annots.add_square(float("nan"), float("inf"), 10.0, 10.0, "QA", "x")

    def test_remove_at_out_of_range_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(PdfEditor.edit(doc))
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                annots.remove_at(annots.get_count() + 50)
