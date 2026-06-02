"""Editor page-ops, metadata, lifecycle, and capability-gap coverage."""
import shutil
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


class TestBaseline:
    def test_page_ops_and_metadata_roundtrip(self, account_form):
        work = tempfile.mktemp(suffix=".pdf")
        out = tempfile.mktemp(suffix=".pdf")
        shutil.copy(account_form, work)
        try:
            with Document.open(work) as doc:
                editor = PdfEditor.edit(doc)
                pages = editor.get_page_collection()
                assert pages.get_count() == 1
                pages.add(width=200.0, height=300.0)
                pages.insert(0, width=150.0, height=150.0)
                pages.swap(0, 1)
                pages.move_to(0, pages.get_count() - 1)
                pages.remove_at(pages.get_count() - 1)
                assert pages.get_count() == 2
                editor.get_metadata().set_title("Edited By Test")
                editor.save_as(out)
                editor.close()
            with Document.open(out) as doc2:
                e2 = PdfEditor.edit(doc2)
                assert e2.get_page_collection().get_count() == 2
                assert e2.get_metadata().get_title() == "Edited By Test"
                e2.close()
        finally:
            inputs.cleanup(work, out)


class TestEdgeCases:
    def test_get_page_out_of_range_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                pages.get_page(999)

    @defect("SDK-009", "add() with negative dims raises IndexOutOfBoundsException, not InvalidArgumentException")
    def test_add_negative_dims_is_invalid_arg(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                pages.add(width=-5.0, height=-5.0)

    @defect("SDK-010", "editor use-after-close raises IndexOutOfBoundsException, not InvalidStateException")
    def test_editor_use_after_close_is_state_error(self, account_form):
        with Document.open(account_form) as doc:
            editor = PdfEditor.edit(doc)
            editor.close()
            with pytest.raises(nutrient_sdk.InvalidStateException):
                editor.get_page_collection().get_count()

    @defect("SDK-008", "second PdfEditor.edit on one Document does not raise AlreadyOpenForEditionException")
    def test_concurrent_edit_is_guarded(self, account_form):
        with Document.open(account_form) as doc:
            PdfEditor.edit(doc)
            with pytest.raises(nutrient_sdk.AlreadyOpenForEditionException):
                PdfEditor.edit(doc)

    @defect("SDK-002", "edit() on a wrong-magic PDF leaks InitializationError(1006), not DocumentError")
    def test_edit_corrupt_pdf_is_documenterror(self):
        path = inputs.truncated_pdf()
        try:
            with pytest.raises(nutrient_sdk.DocumentError):
                with Document.open(path) as doc:
                    PdfEditor.edit(doc).get_page_collection().get_count()
        finally:
            inputs.cleanup(path)


class TestCapabilityGaps:
    @defect("SDK-007", "PdfPage has no set_rotation()/rotate() despite Document Editor entitlement")
    def test_page_rotation_is_settable(self, account_form):
        with Document.open(account_form) as doc:
            page = PdfEditor.edit(doc).get_page_collection().get_first()
            assert hasattr(page, "set_rotation") or hasattr(page, "rotate")
