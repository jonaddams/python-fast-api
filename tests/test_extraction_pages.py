from pathlib import Path

from app.services import extraction
from app.services.extraction import _prepared_pages

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_prepared_pages_renders_each_pdf_page(two_page_scanned_pdf: bytes):
    with _prepared_pages(two_page_scanned_pdf, "two-page.pdf") as (paths, total):
        assert total == 2
        assert len(paths) == 2
        for p in paths:
            with open(p, "rb") as f:
                assert f.read(3) == b"\xff\xd8\xff"  # JPEG magic, every page


def test_prepared_pages_caps_pages_but_reports_total(monkeypatch):
    pdf = (FIXTURES / "usenix-paper.pdf").read_bytes()  # 3 pages
    monkeypatch.setattr(extraction, "MAX_PRERENDER_PAGES", 2)
    with _prepared_pages(pdf, "usenix-paper.pdf") as (paths, total):
        assert total == 3
        assert len(paths) == 2


def test_prepared_pages_honors_explicit_max_pages(two_page_scanned_pdf: bytes):
    with _prepared_pages(two_page_scanned_pdf, "two-page.pdf", max_pages=1) as (
        paths,
        total,
    ):
        assert total == 2
        assert len(paths) == 1


def test_prepared_pages_passes_images_through(sample_image_bytes: bytes):
    with _prepared_pages(sample_image_bytes, "img.png") as (paths, total):
        assert total == 1
        assert len(paths) == 1
        with open(paths[0], "rb") as f:
            assert f.read(8) == sample_image_bytes[:8]
