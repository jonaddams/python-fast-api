import base64
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
                field = fields[i]
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
                field = fields[i]
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


class LicenseFeatureMissing(RuntimeError):
    """Raised when the SDK rejects a call for a missing license feature."""


def detect_fields(pdf_bytes: bytes) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out:
        inp.write(pdf_bytes)
        inp_path, out_path = inp.name, out.name

    try:
        try:
            with Document.open(inp_path) as doc:
                editor = PdfEditor.edit(doc)
                try:
                    input_count = editor.get_form_field_collection().get_count()
                    editor.detect_and_add_form_fields()

                    fields = editor.get_form_field_collection()
                    detected_count = fields.get_count()
                    added = []
                    for i in range(detected_count):
                        f = fields[i]
                        added.append({
                            "name": f.get_full_name(),
                            "type": type(f).__name__,
                        })

                    editor.save_as(out_path)
                finally:
                    editor.close()
        except Exception as ex:
            msg = str(ex)
            if "vision_form" in msg and "Error Code: 3017" in msg:
                raise LicenseFeatureMissing(
                    "Form field detection requires the 'vision_form' license "
                    "entitlement. Your license does not include it."
                ) from ex
            raise

        with open(out_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("ascii")

        return {
            "inputFieldCount": input_count,
            "detectedFieldCount": detected_count,
            "addedFields": added,
            "pdfBase64": pdf_b64,
        }
    finally:
        for p in (inp_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass
