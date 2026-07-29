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
        # NOT wrapped in `with exporter_cls() as ...`: SDK-042 removed the
        # exporters' context-manager protocol in 1.0.9. Passing a bare instance
        # to doc.export() still works and is what app/services/ does, so this
        # stays a real export regression guard rather than becoming an xfail.
        out = tempfile.mktemp(suffix=suffix)
        try:
            with Document.open(account_form) as doc:
                doc.export(out, exporter_cls())
            assert Path(out).stat().st_size > 0
        finally:
            inputs.cleanup(out)

    @pytest.mark.parametrize(
        "exporter_cls", [HtmlExporter, PdfExporter, MarkdownExporter, WordExporter]
    )
    @defect(
        "SDK-042",
        "exporter classes expose no public surface at all in 1.0.9 — no "
        "context-manager protocol, no close(), no settings hook",
        raises=TypeError,
    )
    def test_exporter_supports_context_manager(self, exporter_cls):
        with exporter_cls():
            pass


class TestEdgeCases:
    # SDK-031 is UNVERIFIABLE on 1.0.9, not fixed. Its precondition is a *closed*
    # exporter, and SDK-042 removed close() along with the rest of the exporters'
    # public surface — so `exp.close()` now raises AttributeError before the
    # assertion under test is ever reached.
    #
    # Skipped rather than xfailed deliberately: this test's xfail carries no
    # `raises=`, so an AttributeError in setup would satisfy it and report a
    # green xfail for a defect nobody exercised. Re-enable if 1.0.x restores
    # close(); the assertion body is preserved for that.
    @pytest.mark.sdk_defect
    @pytest.mark.skip(reason="SDK-031 precondition unreachable — SDK-042 removed Exporter.close()")
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
        # No `finally: exp.close()` — SDK-042 removed close(), and an
        # AttributeError in teardown would mask which assertion actually failed.
        exp = HtmlExporter()
        assert hasattr(exp, "set_settings") or "settings" in dir(exp)


class TestSequential:
    def test_failed_export_does_not_leak_state(self, account_form):
        # SDK-003 FIXED in 1.0.9: a failed export no longer poisons process-wide
        # native state, and the use-after-close guard now fires. Kept as a
        # regression guard.
        #
        # Verified the XPASS is genuine, not an artifact of SDK-042: doc.export()
        # with a bare exporter instance still works on 1.0.9, so the ValueError
        # below really is the use-after-close guard rather than a side effect of
        # the exporters losing their public surface.
        #
        # A failed export (bad output path) used to poison the process-wide
        # native state: subsequent Document.open calls raised IOError with the
        # old bad path. Under --forked this is a valid in-process check.
        try:
            with Document.open(account_form) as doc:
                doc.export("/nonexistent_dir_xyz/x.pdf", PdfExporter())
        except Exception:
            pass
        doc2 = Document.open(account_form)
        doc2.close()
        with pytest.raises(ValueError):
            doc2.export(tempfile.mktemp(suffix=".pdf"), PdfExporter())
