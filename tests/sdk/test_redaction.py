import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor, Color
from nutrient_sdk.pdfsavepreferences import PdfSavePreferences

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


def _annots(doc):
    return PdfEditor.edit(doc).get_page_collection().get_page(1).get_annotation_collection()


class TestBaseline:
    def test_apply_redactions_consumes_annotation(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                annots = editor.get_page_collection().get_page(1).get_annotation_collection()
                before = annots.get_count()
                redact = annots.add_redact(50.0, 50.0, 200.0, 30.0)
                redact.set_interior_color(Color.from_argb(255, 0, 0, 0))
                assert annots.get_count() == before + 1
                doc.settings.pdf_settings.save_preferences = PdfSavePreferences.APPLY_REDACTIONS
                editor.save_as(out)
                editor.close()
            with Document.open(out) as doc2:
                assert _annots(doc2).get_count() == before  # redact consumed
        finally:
            inputs.cleanup(out)


class TestFinalizationFootgun:
    @defect("SDK-025", "default NONE save leaves redaction un-applied (content recoverable)")
    def test_default_save_burns_in_content(self, account_form):
        # Without APPLY_REDACTIONS, the redact box is just an annotation; the
        # underlying content is NOT removed. We assert the SAFE behavior
        # (annotation consumed == applied) and expect xfail.
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                annots = editor.get_page_collection().get_page(1).get_annotation_collection()
                before = annots.get_count()
                annots.add_redact(50.0, 50.0, 200.0, 30.0)
                editor.save_as(out)  # no APPLY_REDACTIONS
                editor.close()
            with Document.open(out) as doc2:
                assert _annots(doc2).get_count() == before  # would mean it was applied
        finally:
            inputs.cleanup(out)


class TestEdgeCases:
    def test_get_page_zero_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                pages.get_page(0)

    @defect("SDK-024", "add_redact accepts negative geometry without validation")
    def test_negative_redact_geometry_rejected(self, account_form):
        with Document.open(account_form) as doc:
            annots = _annots(doc)
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                annots.add_redact(50.0, 50.0, -200.0, -30.0)
