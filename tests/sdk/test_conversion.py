import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, DocumentSettings

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


def _write(suffix: str, data: bytes) -> str:
    p = tempfile.mktemp(suffix=suffix)
    Path(p).write_bytes(data)
    return p


class TestBaseline:
    def test_markdown_to_pdf(self):
        src = _write(".md", b"# Hello\n\nThis is **bold**.\n\n- one\n- two\n")
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(src) as doc:
                assert doc.get_underlying_type() == 21  # DOCUMENT_TYPE_MD
                doc.export_as_pdf(out)
            assert Path(out).read_bytes()[:5].startswith(b"%PDF")
        finally:
            inputs.cleanup(src, out)

    def test_pdf_to_html(self, account_form):
        out = tempfile.mktemp(suffix=".html")
        try:
            with Document.open(account_form) as doc:
                doc.export_as_html(out)
            assert Path(out).read_bytes()[:15].startswith(b"<!DOCTYPE html>")
        finally:
            inputs.cleanup(out)


class TestEdgeCases:
    @defect("SDK-002", "empty .docx surfaces as InitializationError(1006), not ConversionError")
    def test_empty_office_file_is_typed(self):
        path = inputs.empty_file(".docx")
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with pytest.raises(nutrient_sdk.NutrientException) as ei:
                with Document.open(path) as doc:
                    doc.export_as_pdf(out)
            assert not isinstance(ei.value, nutrient_sdk.InitializationError)
        finally:
            inputs.cleanup(path, out)

    @defect("SDK-032", "negative conversion timeout accepted without validation")
    def test_negative_timeout_rejected(self):
        src = _write(".md", b"# x\n")
        out = tempfile.mktemp(suffix=".pdf")
        try:
            s = DocumentSettings()
            s.conversion_settings.set_timeout_milliseconds(-1)
            with pytest.raises(nutrient_sdk.NutrientException):
                with Document.open(src, s) as doc:
                    doc.export_as_pdf(out)
        finally:
            inputs.cleanup(src, out)

    def test_unsupported_conversion_is_typed(self, ocr_png):
        # Raster image -> spreadsheet has no tabular source; expect a typed error.
        out = tempfile.mktemp(suffix=".xlsx")
        try:
            with pytest.raises(nutrient_sdk.NutrientException):
                with Document.open(ocr_png) as doc:
                    doc.export_as_spreadsheet(out)
        finally:
            inputs.cleanup(out)


class TestSequential:
    def test_roundtrip_pdf_to_word_to_pdf(self, account_form):
        docx = tempfile.mktemp(suffix=".docx")
        pdf2 = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                doc.export_as_word(docx)
            assert Path(docx).stat().st_size > 0
            with Document.open(docx) as doc:
                doc.export_as_pdf(pdf2)
            assert Path(pdf2).read_bytes()[:5].startswith(b"%PDF")
        finally:
            inputs.cleanup(docx, pdf2)

    def test_repeated_conversions_no_leak(self, account_form):
        for _ in range(20):
            out = tempfile.mktemp(suffix=".md")
            with Document.open(account_form) as doc:
                doc.export_as_markdown(out)
            assert Path(out).stat().st_size > 0
            inputs.cleanup(out)
