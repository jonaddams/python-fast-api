import json
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
            FIELD_TYPE_NAMES = {
                1: "text", 2: "button", 3: "checkbox",
                4: "radio", 5: "combobox", 6: "listbox", 7: "signature",
            }
            for i in range(fields.get_count()):
                field = fields.get_item(i)
                ft = field.get_field_type()
                result.append({
                    "name": field.get_full_name(),
                    "type": type(field).__name__,
                    "fieldType": FIELD_TYPE_NAMES.get(ft, "unknown"),
                    "widgetCount": field.get_widget_count(),
                })
            editor.close()
            return result
    finally:
        os.unlink(inp_path)


def fill_form_fields(pdf_bytes: bytes, values_json: str) -> bytes:
    values: dict[str, str] = json.loads(values_json)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out:
        inp.write(pdf_bytes)
        inp_path, out_path = inp.name, out.name

    try:
        with Document.open(inp_path) as doc:
            editor = PdfEditor.edit(doc)
            fields = editor.get_form_field_collection()
            for i in range(fields.get_count()):
                field = fields.get_item(i)
                name = field.get_full_name()
                if name in values:
                    field.set_value(values[name])
            editor.save_as(out_path)
            editor.close()

        with open(out_path, "rb") as f:
            return f.read()
    finally:
        for p in (inp_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass
