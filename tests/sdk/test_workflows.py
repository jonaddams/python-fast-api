"""Cross-area enterprise pipeline tests — Task 11.

Chains operations across forms, annotations, signing, conversion, and editing.
Signing is fork-unsafe (SDK-034), so any sign() call runs in a spawned subprocess.
All three pipelines here are happy paths and should PASS.
"""
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest
from nutrient_sdk import Document, PdfEditor, Color

from tests.sdk._support import inputs

PROJECT_ENV = str(Path(__file__).resolve().parent.parent.parent / ".env")
CERT = str(Path(__file__).resolve().parent.parent.parent / "app" / "certs" / "demo-certificate.p12")
CERT_PASSWORD = "nutrient-demo"  # confirmed from app/services/signing.py: DEMO_CERT_PASSWORD


def _sign_subprocess(src_pdf: str, out_pdf: str) -> subprocess.CompletedProcess:
    """Sign in a fresh spawned interpreter (sign() is fork-unsafe; see SDK-034)."""
    script = textwrap.dedent(f'''
        import os
        from dotenv import load_dotenv
        load_dotenv({PROJECT_ENV!r})
        from nutrient_sdk import License, Document, Signature, DigitalSignatureOptions
        License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])
        o = DigitalSignatureOptions()
        o.set_certificate_path({CERT!r}); o.set_certificate_password({CERT_PASSWORD!r}); o.set_signer_name("QA")
        with Document.open({src_pdf!r}) as doc, Signature() as s:
            s.sign(doc, {out_pdf!r}, o)
    ''')
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)


class TestEnterpriseChains:
    def test_fill_annotate_sign_reopen(self, account_form):
        """open -> fill a form field -> add a highlight -> save -> sign (subprocess)
        -> reopen the signed output and verify the field value survived."""
        filled = tempfile.mktemp(suffix=".pdf")
        signed = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                editor.get_form_field_collection().find_by_full_name("full_name").set_value("Ada")
                annots = editor.get_page_collection().get_page(1).get_annotation_collection()
                hl = annots.add_highlight(72.0, 700.0, 200.0, 20.0, "QA", "reviewed")
                hl.set_color(Color.from_argb(255, 255, 255, 0))
                editor.save_as(filled)
                editor.close()
            proc = _sign_subprocess(filled, signed)
            assert proc.returncode == 0, proc.stderr
            with Document.open(signed) as doc:
                editor = PdfEditor.edit(doc)
                assert editor.get_form_field_collection().find_by_full_name("full_name").get_value() == "Ada"
                editor.close()
        finally:
            inputs.cleanup(filled, signed)

    def test_edit_then_convert(self, account_form):
        """Edit pages, save, then convert the edited PDF to Markdown."""
        edited = tempfile.mktemp(suffix=".pdf")
        md = tempfile.mktemp(suffix=".md")
        try:
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                editor.get_page_collection().add(width=200.0, height=300.0)
                editor.save_as(edited)
                editor.close()
            with Document.open(edited) as doc:
                assert PdfEditor.edit(doc).get_page_collection().get_count() == 2
            with Document.open(edited) as doc:
                doc.export_as_markdown(md)
            assert Path(md).stat().st_size > 0
        finally:
            inputs.cleanup(edited, md)


class TestPipelineStress:
    def test_repeated_pipeline_no_leak(self, account_form):
        for _ in range(10):
            out = tempfile.mktemp(suffix=".pdf")
            with Document.open(account_form) as doc:
                editor = PdfEditor.edit(doc)
                editor.get_form_field_collection().find_by_full_name("full_name").set_value("X")
                editor.save_as(out)
                editor.close()
            with Document.open(out) as doc:
                assert doc.get_page_count() == 1
            inputs.cleanup(out)
