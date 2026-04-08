import tempfile
import os

from nutrient_sdk import Document, WordEditor


def generate_from_template(
    template_bytes: bytes,
    template_filename: str,
    model_json: str,
) -> bytes:
    with tempfile.NamedTemporaryFile(suffix="-" + template_filename, delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as populated, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out:
        inp.write(template_bytes)
        inp_path, populated_path, out_path = inp.name, populated.name, out.name

    try:
        with Document.open(inp_path) as doc:
            editor = WordEditor.edit(doc)
            editor.apply_template_model(model_json)
            editor.save_with_model_as(populated_path)

        with Document.open(populated_path) as doc:
            doc.export_as_pdf(out_path)

        with open(out_path, "rb") as f:
            return f.read()
    finally:
        for p in (inp_path, populated_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass
