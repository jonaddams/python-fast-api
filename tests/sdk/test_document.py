import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, PdfEditor

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


class TestBaseline:
    def test_open_page_count_settings_export(self, account_form):
        with Document.open(account_form) as doc:
            assert doc.get_page_count() == 1
            assert doc.page_count == 1
            assert doc.get_underlying_type() == 3  # DOCUMENT_TYPE_PDF
            assert type(doc.get_settings()).__name__ == "DocumentSettings"
            editor = PdfEditor.edit(doc)
            pages = editor.get_page_collection()
            assert len(pages) == 1
            p0 = pages[0]
            assert round(p0.get_width(), 1) == 612.0
            assert round(p0.get_height(), 1) == 792.0
            editor.close()
            out = tempfile.mktemp(suffix=".png")
            doc.export_as_image(out)
            assert Path(out).stat().st_size > 0
            inputs.cleanup(out)


class TestEdgeCases:
    @defect("SDK-001", "open(None) raises bare TypeError, not NutrientArgumentNullException")
    def test_open_none_is_typed(self):
        with pytest.raises(nutrient_sdk.NutrientException):
            Document.open(None)

    @defect("SDK-001", "open(bytes) raises bare TypeError, not a typed exception")
    def test_open_bytes_is_typed(self):
        with pytest.raises(nutrient_sdk.NutrientException):
            Document.open(b"%PDF-1.4 fake")

    def test_open_missing_path_is_filenotfound(self):
        with pytest.raises(nutrient_sdk.FileNotFoundException):
            Document.open("/tmp/does_not_exist_xyz_12345.pdf")

    @defect("SDK-002", "wrong-magic file surfaces as InitializationError(1006), not DocumentError")
    def test_open_wrong_magic_is_documenterror(self):
        path = inputs.wrong_magic(".pdf")
        try:
            with pytest.raises(nutrient_sdk.DocumentError):
                Document.open(path)
        finally:
            inputs.cleanup(path)

    @defect("SDK-002", "empty file surfaces as InitializationError(1006), not DocumentError")
    def test_open_empty_file_is_documenterror(self):
        path = inputs.empty_file(".pdf")
        try:
            with pytest.raises(nutrient_sdk.DocumentError):
                Document.open(path)
        finally:
            inputs.cleanup(path)

    @defect("SDK-004", "use-after-close raises bare ValueError, not InvalidStateException")
    def test_use_after_close_is_typed(self, account_form):
        doc = Document.open(account_form)
        doc.close()
        with pytest.raises(nutrient_sdk.InvalidStateException):
            doc.get_page_count()

    def test_double_close_is_noop(self, account_form):
        doc = Document.open(account_form)
        doc.close()
        doc.close()  # must not raise

    def test_export_to_missing_dir_is_typed_io(self, account_form):
        with Document.open(account_form) as doc:
            with pytest.raises(nutrient_sdk.IOError):
                doc.export_as_pdf("/nonexistent_dir_xyz/out.pdf")

    @defect("SDK-006", "export_as_image(None) raises InitializationError(1002), not a null-arg exception")
    def test_export_none_path_is_null_arg(self, account_form):
        with Document.open(account_form) as doc:
            with pytest.raises(nutrient_sdk.NullOrEmptyParameterException):
                doc.export_as_image(None)

    def test_page_index_out_of_range_is_typed(self, account_form):
        with Document.open(account_form) as doc:
            pages = PdfEditor.edit(doc).get_page_collection()
            with pytest.raises(nutrient_sdk.IndexOutOfBoundsException):
                _ = pages[5]


class TestSequential:
    def test_open_export_loop_no_leak(self, account_form):
        for _ in range(30):
            with Document.open(account_form) as doc:
                out = tempfile.mktemp(suffix=".pdf")
                doc.export_as_pdf(out)
                assert Path(out).stat().st_size > 0
                inputs.cleanup(out)

    @defect("SDK-003", "a prior failed open poisons later good opens in the same process")
    def test_failed_open_does_not_poison_next(self, account_form):
        bad = inputs.wrong_magic(".pdf")
        try:
            try:
                Document.open(bad)
            except Exception:
                pass
            with Document.open(account_form) as doc:
                assert doc.get_page_count() == 1
        finally:
            inputs.cleanup(bad)
