import tempfile
import os

from nutrient_sdk import Document


def convert_to_pdf(input_bytes: bytes, original_filename: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix="-" + original_filename, delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out:
        inp.write(input_bytes)
        inp_path, out_path = inp.name, out.name

    try:
        with Document.open(inp_path) as doc:
            doc.export_as_pdf(out_path)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(inp_path)
        os.unlink(out_path)


def pdf_to_html(pdf_bytes: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".html", delete=False) as out:
        inp.write(pdf_bytes)
        inp_path, out_path = inp.name, out.name

    try:
        with Document.open(inp_path) as doc:
            doc.export_as_html(out_path)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(inp_path)
        os.unlink(out_path)


def pdf_to_docx(pdf_bytes: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as out:
        inp.write(pdf_bytes)
        inp_path, out_path = inp.name, out.name

    try:
        with Document.open(inp_path) as doc:
            doc.export_as_word(out_path)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(inp_path)
        os.unlink(out_path)


def pdf_to_xlsx(pdf_bytes: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as inp, \
         tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as out:
        inp.write(pdf_bytes)
        inp_path, out_path = inp.name, out.name

    try:
        with Document.open(inp_path) as doc:
            doc.export_as_spreadsheet(out_path)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(inp_path)
        os.unlink(out_path)
