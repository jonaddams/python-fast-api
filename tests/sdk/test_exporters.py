"""Exporter matrix baseline + orphaned-settings/format/lifecycle defects."""
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import (
    Document, HtmlExporter, PdfExporter, MarkdownExporter, WordExporter,
    ImageExportFormat,
)

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect


class TestBaseline:
    @pytest.mark.parametrize("exporter_cls, suffix", [
        (HtmlExporter, ".html"),
        (PdfExporter, ".pdf"),
        (MarkdownExporter, ".md"),
        (WordExporter, ".docx"),
    ])
    def test_generic_export(self, account_form, exporter_cls, suffix):
        out = tempfile.mktemp(suffix=suffix)
        try:
            with Document.open(account_form) as doc:
                with exporter_cls() as exporter:
                    doc.export(out, exporter)
            assert Path(out).stat().st_size > 0
        finally:
            inputs.cleanup(out)


class TestEdgeCases:
    @defect(
        "SDK-031",
        "export() does not guard a closed exporter; sends NULL handle -> native crash "
        "(raises InitializationError(1006), not a clean ValueError)",
    )
    def test_export_with_closed_exporter_is_typed(self, account_form):
        # We assert the CLEAN expected type only (ValueError).
        # InitializationError IS a NutrientException, so pytest.raises(NutrientException)
        # would catch it and produce a spurious xpass.  The defect is that the SDK
        # surfaces InitializationError(1006) instead of a clean ValueError.
        out = tempfile.mktemp(suffix=".pdf")
        exp = PdfExporter()
        exp.close()
        with Document.open(account_form) as doc:
            with pytest.raises(ValueError):
                doc.export(out, exp)
        inputs.cleanup(out)

    @defect("SDK-002", "None exporter -> InitializationError(1006), not a typed null-arg exception")
    def test_none_exporter_is_typed(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        with Document.open(account_form) as doc:
            with pytest.raises(nutrient_sdk.NutrientArgumentNullException):
                doc.export(out, None)
        inputs.cleanup(out)

    def test_image_export_formats_available(self):
        # SDK-030 (NAPY-16) FIXED in 1.0.8: ImageExportFormat now exposes all
        # advertised formats, not just TIFF. Kept as a regression guard.
        names = {m.name for m in ImageExportFormat}
        assert {"PNG", "JPEG", "BMP", "TIFF"}.issubset(names)

    @defect("SDK-029", "no Python API attaches a *Settings object to any exporter")
    def test_exporter_accepts_settings(self):
        exp = HtmlExporter()
        try:
            assert hasattr(exp, "set_settings") or "settings" in dir(exp)
        finally:
            exp.close()


class TestSequential:
    @defect("SDK-003", "a prior failed export bypasses the use-after-close guard for later calls")
    def test_failed_export_does_not_leak_state(self, account_form):
        # A failed export (bad output path) poisons the process-wide native state:
        # subsequent Document.open calls raise IOError with the old bad path.
        # Under --forked this is a valid in-process check.
        try:
            with Document.open(account_form) as doc:
                doc.export("/nonexistent_dir_xyz/x.pdf", PdfExporter())
        except Exception:
            pass
        doc2 = Document.open(account_form)
        doc2.close()
        with pytest.raises(ValueError):
            doc2.export(tempfile.mktemp(suffix=".pdf"), PdfExporter())
