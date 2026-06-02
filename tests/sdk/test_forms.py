"""Form list/fill/detect baseline + validation/typing defect coverage."""
import tempfile

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


class TestBaseline:
    def test_list_and_fill(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                fields = editor.get_form_field_collection()
                assert fields.get_count() == 15
                target = fields.find_by_full_name("full_name")
                assert target.get_field_type() == 1  # int, not enum
                target.set_value("Ada Lovelace")
                assert target.get_value() == "Ada Lovelace"
                editor.save_as(out)
                editor.close()
        finally:
            inputs.cleanup(out)

    def test_detect_adds_fields(self, detection_pdf):
        with Document.open(detection_pdf) as doc:
            editor = PdfEditor.edit(doc)
            fields = editor.get_form_field_collection()
            assert fields.get_count() == 0
            editor.detect_and_add_form_fields()
            assert fields.get_count() > 0  # ~13 at default confidence
            editor.close()


class TestEdgeCases:
    @defect("SDK-013", "collection[i] out-of-range raises builtin IndexError, not IndexOutOfBoundsException")
    def test_index_out_of_range_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            with pytest.raises(nutrient_sdk.NutrientException):
                _ = fields[999]

    @defect("SDK-014", "find_by_full_name returns None silently for a missing field")
    def test_missing_field_lookup_raises(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            with pytest.raises(nutrient_sdk.NutrientException):
                fields.find_by_full_name("does_not_exist")

    @defect("SDK-015", "set_value(None) silently accepted on a text field")
    def test_set_value_none_rejected(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            with pytest.raises(nutrient_sdk.NutrientException):
                fields.find_by_full_name("full_name").set_value(None)

    @defect("SDK-016", "invalid radio/combo option accepted without validation")
    def test_invalid_option_rejected(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            with pytest.raises(nutrient_sdk.NutrientException):
                fields.find_by_full_name("account_type").set_value("not_an_option")

    @defect("SDK-017", "field is always base PdfFormField, never the typed subtype")
    def test_field_is_typed_subtype(self, account_form):
        with Document.open(account_form) as doc:
            fields = PdfEditor.edit(doc).get_form_field_collection()
            radio = fields.find_by_full_name("account_type")
            assert type(radio).__name__ != "PdfFormField"

    @defect("SDK-018", "confidence_threshold accepts out-of-[0,1] values unvalidated")
    def test_confidence_out_of_range_rejected(self, account_form):
        with Document.open(account_form) as doc:
            frs = doc.get_settings().get_form_recognition_settings()
            with pytest.raises(nutrient_sdk.NutrientException):
                frs.set_confidence_threshold(5.0)
