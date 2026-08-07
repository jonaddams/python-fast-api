"""Unit tests for the OCR Code snippet. Pure — no SDK, no network, no fixtures.

The rule these enforce comes from _build_code's fix rounds in structured.py:
string-matching a snippet is what let `request.schema = SCHEMA` ship against a
name nothing assigned. A snippet whose entire purpose is being copied verbatim
has to be compiled, and every name it references has to be bound.
"""

import ast
import builtins

from app.services.extraction import _build_ocr_code

JSON_ECHO = {"languages": "eng", "outputFormat": "json"}
MARKDOWN_ECHO = {"languages": "eng", "outputFormat": "markdown"}


def unbound_names(code: str) -> set[str]:
    """Every Name the snippet reads that nothing imports, assigns or binds.

    compile() only proves the snippet parses; this proves it would not raise
    NameError on the first run — the class of bug that actually shipped once.
    """
    tree = ast.parse(code)
    bound: set[str] = set(dir(builtins))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                bound.add(node.id)
            else:
                used.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    return used - bound


class TestBuildOcrCode:
    def test_json_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_ocr_code("scanned-invoice.pdf", JSON_ECHO, table_detection=True)
        compile(code, "<snippet>", "exec")
        assert unbound_names(code) == set()

    def test_markdown_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_ocr_code("scan.pdf", MARKDOWN_ECHO, table_detection=True)
        compile(code, "<snippet>", "exec")
        assert unbound_names(code) == set()

    def test_the_snippet_reflects_the_run_that_produced_it(self):
        code = _build_ocr_code(
            "scan.pdf",
            {"languages": "eng+deu+fra", "outputFormat": "json"},
            table_detection=False,
        )
        assert 'set_default_languages("eng+deu+fra")' in code
        assert "set_enable_table_detection(False)" in code
        assert "scan.pdf" in code

    def test_only_the_markdown_branch_sets_the_output_format(self):
        md = _build_ocr_code("scan.pdf", MARKDOWN_ECHO, table_detection=True)
        js = _build_ocr_code("scan.pdf", JSON_ECHO, table_detection=True)
        assert "VisionOutputFormat.MARKDOWN" in md
        assert "VisionOutputFormat" not in js

    def test_the_markdown_branch_joins_pages_with_the_real_separator(self):
        # Not a lookalike string: the studio's own PAGE_BREAK, so what a
        # prospect runs produces what the studio showed them.
        from app.services.extraction import PAGE_BREAK

        code = _build_ocr_code("scan.pdf", MARKDOWN_ECHO, table_detection=True)
        assert repr(PAGE_BREAK) in code
        assert "json.loads" not in code  # markdown does not merge elements

    def test_the_json_branch_rewrites_page_number_and_reading_order(self):
        # The trap the merge exists for: each per-page call reports
        # pageNumber=1 and restarts readingOrder at 0.
        code = _build_ocr_code("scan.pdf", JSON_ECHO, table_detection=True)
        assert 'element["pageNumber"] = page_idx' in code
        assert 'element["readingOrder"] = next_order' in code

    def test_the_glob_sorts_numerically_and_falls_back_to_the_single_page_name(self):
        # Two ways this snippet ships silently broken: sorted(glob(...)) is
        # lexicographic, so page-10 lands before page-2; and a single-page
        # document is written to page.jpg with no suffix at all, so the glob
        # returns nothing and the snippet prints an empty list. The studio's
        # corpus is short scans, so the second is the likelier hit.
        code = _build_ocr_code("scan.pdf", JSON_ECHO, table_detection=True)
        assert "int(re.search" in code
        assert 'paths = paths or ["page.jpg"]' in code

    def test_the_snippet_frames_the_prerender_as_capability_not_defect(self):
        # Prospect-facing material. Naming our own open SDK issues in it
        # advertises a known bug in the artefact meant to prove the SDK works.
        code = _build_ocr_code("scan.pdf", JSON_ECHO, table_detection=True)
        assert "Adaptive OCR reads page images" in code
        for leak in ("NAPY", "workaround", "bug", "fails"):
            assert leak not in code

    def test_a_filename_containing_a_quote_still_compiles(self):
        # Filenames are user-supplied. Interpolating one raw into a double-quoted
        # literal is a one-character break, so the name goes through json.dumps.
        code = _build_ocr_code('he"llo\\scan.pdf', JSON_ECHO, table_detection=True)
        compile(code, "<snippet>", "exec")
