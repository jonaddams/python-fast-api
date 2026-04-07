import tempfile
import os

from nutrient_sdk import Document, PdfEditor


def list_form_fields(pdf_bytes: bytes) -> list[dict[str, str]]:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp:
        inp.write(pdf_bytes)
        inp_path = inp.name

    try:
        with Document.open(inp_path) as doc:
            editor = PdfEditor.edit(doc)
            fields = editor.get_form_field_collection()
            result = []
            for i in range(fields.get_count()):
                field = fields.get_item(i)
                result.append({
                    "name": field.get_full_name(),
                    "type": type(field).__name__,
                })
            editor.close()
            return result
    finally:
        os.unlink(inp_path)
