import tempfile
import os

from nutrient_sdk import Document, PdfEditor


def get_metadata(pdf_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp:
        inp.write(pdf_bytes)
        inp_path = inp.name

    try:
        with Document.open(inp_path) as doc:
            editor = PdfEditor.edit(doc)
            xmp = editor.get_metadata().get_xmp()
            editor.close()
            return xmp
    finally:
        os.unlink(inp_path)
