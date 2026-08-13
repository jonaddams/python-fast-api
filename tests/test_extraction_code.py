"""Unit tests for the OCR Code snippet. Pure — no SDK, no network, no fixtures.

The rule these enforce comes from _build_code's fix rounds in structured.py:
string-matching a snippet is what let `request.schema = SCHEMA` ship against a
name nothing assigned. A snippet whose entire purpose is being copied verbatim
has to be compiled, and every name it references has to be bound.
"""

import ast
import builtins

from app.services.extraction import (
    _build_describe_code,
    _build_handwriting_code,
    _build_markdown_code,
    _build_ocr_code,
    _build_tables_code,
)

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
        #
        # Both traps stay pinned now that the pages live in a temp dir: the
        # sort key is unchanged, and the fallback is `base` — the same
        # os.path.join(pages_dir, "page.jpg") that export_as_image was handed,
        # so it names the file that actually exists.
        code = _build_ocr_code("scan.pdf", JSON_ECHO, table_detection=True)
        assert 'key=lambda p: int(re.search(r"-(\\d+)\\.jpg$", p).group(1))' in code
        assert 'base = os.path.join(pages_dir, "page.jpg")' in code
        assert "paths = paths or [base]" in code

    def test_the_snippet_writes_its_pages_to_a_temp_dir_not_the_cwd(self):
        """Fixed CWD names OCR the wrong document, silently, on the second run.

        A prospect runs the snippet on a 3-page PDF, then on a 1-page PDF in
        the same directory. page-1..3.jpg are still on disk, so run 2's glob
        returns them, `paths` is non-empty, the single-page fallback never
        fires — and the snippet OCRs the PREVIOUS document while printing it
        as the current one. Exit 0, no warning. Reproduced live on the old
        snippet; trying a second document is the first thing a prospect does.

        A private directory also keeps the glob away from any unrelated
        page-cover.jpg, on which the numeric sort key raises AttributeError.
        """
        for echo in (JSON_ECHO, MARKDOWN_ECHO):
            code = _build_ocr_code("scan.pdf", echo, table_detection=True)
            assert "with tempfile.TemporaryDirectory() as pages_dir:" in code

            # Structural, not string-matching: every path the snippet writes to
            # or globs must be rooted in pages_dir. A bare literal would be a
            # CWD write however the surrounding lines are worded.
            rooted = []
            for node in ast.walk(ast.parse(code)):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                is_export = func.attr == "export_as_image"
                is_glob = func.attr == "glob" and getattr(func.value, "id", "") == "glob"
                if is_export or is_glob:
                    rooted.append(ast.unparse(node.args[0]))
            assert len(rooted) == 2, rooted
            for target in rooted:
                assert target == "base" or target.startswith(
                    "os.path.join(pages_dir"
                ), target

    def test_every_page_is_read_before_the_temp_dir_closes(self):
        # The JPEGs vanish when the TemporaryDirectory block exits, so the
        # Vision loop has to be inside it. Hoisting the loop out for tidiness
        # would leave a snippet that raises on its own generated paths.
        for echo in (JSON_ECHO, MARKDOWN_ECHO):
            code = _build_ocr_code("scan.pdf", echo, table_detection=True)
            tree = ast.parse(code)
            temp_dir_blocks = [
                node
                for node in tree.body
                if isinstance(node, ast.With)
                and "tempfile.TemporaryDirectory()" in ast.unparse(node.items[0].context_expr)
            ]
            assert len(temp_dir_blocks) == 1
            body = ast.unparse(temp_dir_blocks[0])
            assert "raws.append(Vision.set(page).extract_content())" in body

    def test_the_stdlib_imports_are_one_per_line_and_accurate_per_branch(self):
        # PEP 8, in code a customer pastes into their project. And json is only
        # needed by the merge, which the markdown branch does not do.
        js = _build_ocr_code("scan.pdf", JSON_ECHO, table_detection=True)
        md = _build_ocr_code("scan.pdf", MARKDOWN_ECHO, table_detection=True)
        assert js.startswith("import glob\nimport json\nimport os\nimport re\nimport tempfile\n")
        assert md.startswith("import glob\nimport os\nimport re\nimport tempfile\n")
        assert "import json" not in md

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


class TestBuildTablesCode:
    def test_pdf_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_tables_code("invoice.pdf", is_pdf=True)
        compile(code, "<tables-snippet>", "exec")
        assert unbound_names(code) == set()

    def test_image_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_tables_code("scan.png", is_pdf=False)
        compile(code, "<tables-snippet>", "exec")
        assert unbound_names(code) == set()

    def test_pages_are_written_to_a_directory_the_snippet_owns(self):
        # The #35 bug: exporting to page.jpg in the CWD let a stale glob from a
        # previous 3-page run make `paths` non-empty on a 1-page document, so the
        # fallback never fired and it OCR'd the PREVIOUS document, exit code 0.
        code = _build_tables_code("invoice.pdf", is_pdf=True)
        assert "tempfile.TemporaryDirectory()" in code
        assert 'os.path.join(pages_dir, "page.jpg")' in code

    def test_image_input_does_not_describe_a_prerender_that_never_happens(self):
        # _build_ocr_code receives only `filename`, so it cannot make the %PDF
        # check _prepared_pages makes: POST a PNG and its snippet describes a
        # rasterisation that did not occur. This one takes is_pdf.
        code = _build_tables_code("scan.png", is_pdf=False)
        assert "export_as_image" not in code
        assert "TemporaryDirectory" not in code

    def test_snippet_states_the_page_cap(self):
        # Production caps at MAX_PRERENDER_PAGES = 10; a snippet that processes
        # every page hands a prospect more output than the panel showed.
        code = _build_tables_code("invoice.pdf", is_pdf=True)
        assert "10" in code
        assert "MAX_PRERENDER_PAGES" in code or "first 10" in code

    def test_snippet_filters_to_table_elements(self):
        code = _build_tables_code("invoice.pdf", is_pdf=True)
        assert '"table"' in code

    def test_filename_with_a_quote_does_not_break_the_literal(self):
        code = _build_tables_code('we"ird.pdf', is_pdf=True)
        compile(code, "<tables-snippet>", "exec")


class TestBuildDescribeCode:
    def test_pdf_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_describe_code(
            "invoice.pdf", is_pdf=True, prompt=None, level="standard", provider="claude"
        )
        compile(code, "<describe-snippet>", "exec")
        assert unbound_names(code) == set()

    def test_image_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_describe_code(
            "scan.png", is_pdf=False, prompt=None, level="detailed", provider="openai"
        )
        compile(code, "<describe-snippet>", "exec")
        assert unbound_names(code) == set()

    def test_snippet_states_the_page_one_limit(self):
        # describe_image wraps _prepared_input, which passes max_pages=1. A snippet
        # implying whole-document coverage is a lie a prospect would paste into
        # their own project.
        code = _build_describe_code(
            "invoice.pdf", is_pdf=True, prompt=None, level="standard", provider="claude"
        )
        assert "page 1" in code.lower() or "first page" in code.lower()

    def test_image_input_does_not_describe_a_prerender_that_never_happens(self):
        code = _build_describe_code(
            "scan.png", is_pdf=False, prompt=None, level="standard", provider="claude"
        )
        assert "export_as_image" not in code
        assert "TemporaryDirectory" not in code

    def test_pdf_input_owns_the_directory_it_writes_into(self):
        # The #35 bug: a fixed name in the CWD let a stale file from a previous
        # run be described instead, exit code 0.
        code = _build_describe_code(
            "invoice.pdf", is_pdf=True, prompt=None, level="standard", provider="claude"
        )
        assert "tempfile.TemporaryDirectory()" in code

    def test_level_and_provider_interpolate_from_the_run(self):
        code = _build_describe_code(
            "x.pdf", is_pdf=True, prompt=None, level="detailed", provider="openai"
        )
        assert "DescriptionLevel.DETAILED" in code
        assert "VlmProvider.OPEN_AI" in code
        other = _build_describe_code(
            "x.pdf", is_pdf=True, prompt=None, level="standard", provider="claude"
        )
        assert "DescriptionLevel.STANDARD" in other
        assert "VlmProvider.CLAUDE" in other

    def test_no_prompt_means_no_prompt_call(self):
        code = _build_describe_code(
            "x.pdf", is_pdf=True, prompt=None, level="standard", provider="claude"
        )
        assert "set_standard_prompt" not in code

    def test_prompt_with_a_quote_and_a_newline_survives(self):
        # The prompt is USER-SUPPLIED. The allowlist argument that justifies raw
        # interpolation for `languages` in _build_ocr_code does not apply here.
        code = _build_describe_code(
            "x.pdf",
            is_pdf=True,
            prompt='Say "hello"\nthen stop',
            level="standard",
            provider="claude",
        )
        compile(code, "<describe-snippet>", "exec")
        assert "set_standard_prompt" in code
        assert unbound_names(code) == set()

    def test_pdf_branch_globs_the_multipage_export_instead_of_opening_a_bare_path(self):
        # export_as_image() writes ALL pages: page-1.jpg, page-2.jpg, ... and
        # never the bare base path for a multi-page PDF (that path exists only
        # in the single-page case). Opening a hardcoded "page-1.jpg" (or any
        # bare base path) unconditionally raises FileNotFoundError on a real
        # multi-page document, which is exactly the bug a prospect would hit
        # pasting this into their own multi-page-PDF project. Assert on the
        # emitted source rather than running the SDK.
        code = _build_describe_code(
            "invoice.pdf", is_pdf=True, prompt=None, level="standard", provider="claude"
        )
        assert 'glob.glob(os.path.join(pages_dir, "page-*.jpg"))' in code
        assert 'key=lambda p: int(re.search(r"-(\\d+)\\.jpg$", p).group(1))' in code
        assert "paths = paths or [base]" in code
        assert "Document.open(paths[0])" in code
        assert 'Document.open("page-1.jpg")' not in code
        assert "Document.open(page_one)" not in code


class TestBuildHandwritingCode:
    def test_local_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_handwriting_code("scan.pdf", engine="ICR", provider=None)
        compile(code, "<snippet>", "exec")
        assert unbound_names(code) == set()

    def test_vlm_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_handwriting_code("scan.pdf", engine="VLM", provider="claude")
        compile(code, "<snippet>", "exec")
        assert unbound_names(code) == set()

    def test_engine_interpolates_from_the_run(self):
        assert "VisionEngine.ICR" in _build_handwriting_code(
            "s.pdf", engine="ICR", provider=None
        )
        assert "VisionEngine.VLM_ENHANCED_ICR" in _build_handwriting_code(
            "s.pdf", engine="VLM", provider="claude"
        )

    def test_local_snippet_configures_no_provider(self):
        # Local ICR's whole claim is that nothing leaves the machine. A snippet
        # that sets an API key would contradict the feature it demonstrates.
        code = _build_handwriting_code("s.pdf", engine="ICR", provider=None)
        assert "api_key" not in code
        assert "VlmProvider" not in code

    def test_vlm_snippet_configures_the_provider_it_ran_with(self):
        claude = _build_handwriting_code("s.pdf", engine="VLM", provider="claude")
        assert "VlmProvider.CLAUDE" in claude
        assert "ANTHROPIC_API_KEY" in claude
        openai = _build_handwriting_code("s.pdf", engine="VLM", provider="openai")
        assert "VlmProvider.OPEN_AI" in openai
        assert "OPENAI_API_KEY" in openai

    def test_vlm_snippet_with_no_provider_targets_the_local_default(self):
        # /vlm's own default (provider unset) is _run_vision's `if provider:`
        # guard: no provider is set at all and the SDK talks to a local VLM
        # server. A snippet that assumed Claude here would fail without
        # ANTHROPIC_API_KEY for a reader who never configured a provider —
        # and an unused `from nutrient_sdk.vlmprovider import VlmProvider`
        # would be a defect of its own in a snippet read as much as run.
        code = _build_handwriting_code("s.pdf", engine="VLM", provider=None)
        assert "VisionEngine.VLM_ENHANCED_ICR" in code
        assert "VlmProvider" not in code
        assert "api_key" not in code
        assert "ANTHROPIC_API_KEY" not in code
        compile(code, "<snippet>", "exec")
        assert unbound_names(code) == set()

    def test_pages_are_written_to_a_directory_the_snippet_owns(self):
        # The #63 bug, pinned: a snippet that globs page-*.jpg out of the CWD
        # picks up the PREVIOUS document's pages and silently reads the wrong
        # file at exit code 0.
        code = _build_handwriting_code("s.pdf", engine="ICR", provider=None)
        assert "tempfile.TemporaryDirectory()" in code
        assert 'glob.glob(os.path.join(pages_dir, "page-*.jpg"))' in code

    def test_filename_with_a_quote_does_not_break_the_literal(self):
        code = _build_handwriting_code('we"ird.pdf', engine="ICR", provider=None)
        compile(code, "<snippet>", "exec")


class TestBuildMarkdownCode:
    def test_pdf_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_markdown_code("invoice.pdf", is_pdf=True, provider="claude")
        compile(code, "<markdown-snippet>", "exec")
        assert unbound_names(code) == set()

    def test_image_snippet_is_valid_python_with_every_name_bound(self):
        code = _build_markdown_code("scan.png", is_pdf=False, provider="openai")
        compile(code, "<markdown-snippet>", "exec")
        assert unbound_names(code) == set()

    def test_pages_are_written_to_a_directory_the_snippet_owns(self):
        # The #35 bug: exporting to page.jpg in the CWD let a stale glob from a
        # previous 3-page run make `paths` non-empty on a 1-page document, so the
        # fallback never fired and it OCR'd the PREVIOUS document, exit code 0.
        code = _build_markdown_code("invoice.pdf", is_pdf=True, provider="claude")
        assert "tempfile.TemporaryDirectory()" in code
        assert 'os.path.join(pages_dir, "page.jpg")' in code

    def test_image_input_does_not_describe_a_prerender_that_never_happens(self):
        code = _build_markdown_code("scan.png", is_pdf=False, provider="claude")
        assert "export_as_image" not in code
        assert "TemporaryDirectory" not in code

    def test_snippet_states_the_page_cap(self):
        # Production caps at MAX_PRERENDER_PAGES = 10; a snippet that claims
        # every page hands a prospect more output than the panel showed.
        code = _build_markdown_code("invoice.pdf", is_pdf=True, provider="claude")
        assert "10" in code
        assert "MAX_PRERENDER_PAGES" in code or "first 10" in code

    def test_multipage_output_is_joined_with_the_real_separator(self):
        # Not a lookalike string: the studio's own PAGE_BREAK, so what a
        # prospect runs produces what the studio showed them.
        from app.services.extraction import PAGE_BREAK

        code = _build_markdown_code("invoice.pdf", is_pdf=True, provider="claude")
        assert repr(PAGE_BREAK) in code

    def test_provider_interpolates_from_the_run(self):
        claude = _build_markdown_code("x.pdf", is_pdf=True, provider="claude")
        assert "VlmProvider.CLAUDE" in claude
        assert "ANTHROPIC_API_KEY" in claude
        openai = _build_markdown_code("x.pdf", is_pdf=True, provider="openai")
        assert "VlmProvider.OPEN_AI" in openai
        assert "OPENAI_API_KEY" in openai

    def test_engine_matches_the_one_extract_markdown_actually_runs(self):
        # extract_markdown calls _run_with_prerender(..., "VLM", ...), and
        # _run_vision's engine_map sends "VLM" to VLM_ENHANCED_ICR — not the
        # nonexistent VisionEngine.VLM. Pin the constant that actually exists.
        code = _build_markdown_code("x.pdf", is_pdf=True, provider="claude")
        assert "VisionEngine.VLM_ENHANCED_ICR" in code

    def test_pdf_branch_globs_the_multipage_export_instead_of_opening_a_bare_path(self):
        code = _build_markdown_code("invoice.pdf", is_pdf=True, provider="claude")
        assert 'glob.glob(os.path.join(pages_dir, "page-*.jpg"))' in code
        assert 'key=lambda p: int(re.search(r"-(\\d+)\\.jpg$", p).group(1))' in code
        assert "paths = paths or [base]" in code

    def test_filename_with_a_quote_does_not_break_the_literal(self):
        code = _build_markdown_code('we"ird.pdf', is_pdf=True, provider="claude")
        compile(code, "<markdown-snippet>", "exec")
