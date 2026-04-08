import json
import tempfile
import os

from nutrient_sdk import Document, PdfEditor, Color
from nutrient_sdk.pdfsavepreferences import PdfSavePreferences


def apply_redactions(pdf_bytes: bytes, regions_json: str) -> bytes:
    regions: list[dict] = json.loads(regions_json)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out:
        inp.write(pdf_bytes)
        inp_path, out_path = inp.name, out.name

    try:
        with Document.open(inp_path) as doc:
            editor = PdfEditor.edit(doc)
            pages = editor.get_page_collection()

            for region in regions:
                page_index = region.get("page", 0)
                page = pages.get_item(page_index)
                annotations = page.get_annotation_collection()

                redact = annotations.add_redact(
                    float(region["x"]),
                    float(region["y"]),
                    float(region["width"]),
                    float(region["height"]),
                )
                redact.set_interior_color(Color.from_argb(255, 0, 0, 0))

            doc.settings.pdf_settings.save_preferences = PdfSavePreferences.APPLY_REDACTIONS
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
