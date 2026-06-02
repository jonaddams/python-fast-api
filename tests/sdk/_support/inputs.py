"""Generators for malformed / edge-case inputs, written to temp files."""
import os
import tempfile
from pathlib import Path


def _tmp(suffix: str, data: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def empty_file(suffix: str = ".pdf") -> str:
    """A zero-byte file with the given extension."""
    return _tmp(suffix, b"")


def wrong_magic(suffix: str = ".pdf") -> str:
    """A file whose contents are not the format its extension claims."""
    return _tmp(suffix, b"this is definitely not a real document at all")


def truncated_pdf() -> str:
    """A file that starts like a PDF then stops."""
    return _tmp(".pdf", b"%PDF-1.7\n1 0 obj<< /Type /Catalog")


def png_renamed_pdf(fixtures_dir: Path) -> str:
    """A real PNG's bytes under a .pdf extension."""
    data = (fixtures_dir / "input_ocr_multiple_languages.png").read_bytes()
    return _tmp(".pdf", data)


def unicode_named_copy(fixtures_dir: Path) -> str:
    """A real PDF copied to a path with a unicode + spaces filename."""
    data = (fixtures_dir / "account-registration-form.pdf").read_bytes()
    d = tempfile.mkdtemp()
    path = os.path.join(d, "ünïcödé 文件 name.pdf")
    Path(path).write_bytes(data)
    return path


def cleanup(*paths: str) -> None:
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass
