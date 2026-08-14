import contextlib
import glob
import json
import re
import tempfile
import os
from collections.abc import Iterator

from nutrient_sdk import (
    Document,
    ImageExportFormat,
    Vision,
    VisionEngine,
    VisionFeatures,
    VisionOutputFormat,
    DescriptionLevel,
)

from app.services.geometry import normalize_bbox


class LocalVlmUnavailable(RuntimeError):
    """Raised when VLM_ENHANCED_ICR cannot reach its local model server."""


# `_vision_keep_alive` removed 2026-05-29 after stress-testing on
# nutrient-sdk 1.0.6 showed the native GC SIGSEGV no longer reproduces.
# Re-add if segfaults reappear.

# The license key was regenerated 2026-05-28 with the `vision_form`
# entitlement, so the full feature set is available (the previous FORM
# opt-out is gone; tests/sdk/test_vision.py guards the entitlement live).
_LICENSED_VISION_FEATURES = VisionFeatures.ALL.value

# SDK 1.0.8 regression (NAPY-20 / SDK-041): requesting a narrow VisionFeatures
# bitmask (e.g. TABLE or KEY_VALUE_REGION alone) makes extract_content() fail with
# "AiTextCorrection: documentLayout not received from dependencies (Error Code: 3024)"
# — the document-graph pipeline needs an internal documentLayout context that a narrow
# selection no longer provides. A narrow selection worked on 1.0.6. Workaround: request
# ALL features and filter the merged elements down to the type we want (table elements /
# key-value regions). When NAPY-20 is fixed, the table/fields paths can go back to the
# narrow feature for efficiency.
_DOCGRAPH_FEATURES = VisionFeatures.ALL.value

# Scanned PDFs are pre-rendered one JPEG per page; cap how many pages a single
# request may process (VLM engines make one provider API call per page).
MAX_PRERENDER_PAGES = 10

# JPEG quality for the pre-render. JPEG (not TIFF/PNG) because OpenAI's VLM API
# rejects TIFF and an oversized PNG blows past Anthropic's 10 MB request cap
# after the SDK's internal upload re-encode; q90 keeps each page ~1 MB at full
# rasterization resolution. (Don't change the format without re-running both
# provider paths — on-disk size != wire size.)
_PRERENDER_JPEG_QUALITY = 90

PAGE_BREAK = "\n\n---\n\n"


def merge_element_pages(raw_jsons: list[str]) -> dict:
    """Merge per-page Vision extract_content payloads into one document.

    Each per-page Vision call reports pageNumber=1 and restarts readingOrder
    at 0, so both fields are rewritten: pageNumber becomes the true 1-based
    page index, and readingOrder becomes globally sequential across the whole
    document (preserving each page's internal order). Without the readingOrder
    rewrite, the readingOrder sort in _format_extraction_result would
    interleave pages.
    """
    merged: list[dict] = []
    pages: list[dict] = []
    next_order = 0
    for page_idx, raw in enumerate(raw_jsons, start=1):
        payload = json.loads(raw)

        # Page dimensions travel in a top-level `metadata` array. They are the
        # only way to convert raster-pixel bounds into the fractional citation
        # coords the viewer draws, so they must survive the merge. Each
        # per-page call reports pageNumber=1, so the index is authoritative.
        for meta in payload.get("metadata", []) or []:
            width, height = meta.get("width"), meta.get("height")
            if width and height:
                pages.append({"page": page_idx, "width": width, "height": height})

        elements = payload.get("elements", [])
        elements.sort(key=lambda e: e.get("readingOrder", 0))
        for el in elements:
            el["pageNumber"] = page_idx
            el["readingOrder"] = next_order
            next_order += 1
            merged.append(el)
    return {"elements": merged, "pages": pages}


def merge_markdown_pages(texts: list[str]) -> str:
    """Join per-page Markdown with horizontal-rule page breaks."""
    return PAGE_BREAK.join(texts)


def _collect_rendered_jpegs(base_path: str) -> list[str]:
    """Return the JPEG files export_as_image() wrote, in page order.

    A single-page document is written to base_path itself; a multi-page
    document is written one JPEG per page as `<stem>-<1-based>.<ext>` (verified
    on 1.0.8), with no bare base_path. Sort the suffixed files numerically so
    page 10 follows page 9 rather than page 1.
    """
    stem, ext = os.path.splitext(base_path)
    suffixed = glob.glob(glob.escape(stem) + "-*" + ext)
    if suffixed:
        return sorted(
            suffixed,
            key=lambda p: int(re.search(rf"-(\d+){re.escape(ext)}$", p).group(1)),
        )
    return [base_path]  # single-page: written directly to base_path


@contextlib.contextmanager
def _prepared_pages(
    image_bytes: bytes,
    original_filename: str,
    max_pages: int | None = None,
) -> Iterator[tuple[list[str], int]]:
    """Write bytes to temp storage and yield Vision-safe per-page image paths.

    PDFs are pre-rendered first: image-only PDFs fail Vision's InputImage
    stage (NAPY-8), and once one Vision call fails the SDK enters a
    process-wide bad state where every subsequent call fails identically
    (NAPY-7). Pre-rendering avoids triggering that path.

    export_as_image() rasterizes every page to its own JPEG in one call,
    honoring the `.jpg` extension (NAPY-16, fixed in 1.0.8 — earlier versions
    ignored the extension and wrote a multi-frame TIFF that needed a Pillow
    re-encode). JPEG keeps each page ~1 MB (see _PRERENDER_JPEG_QUALITY).

    Yields (paths, total_pages): up to max_pages (default MAX_PRERENDER_PAGES)
    JPEG paths in page order, plus the document's full page count so callers
    can report truncation. Non-PDF inputs yield ([original_path], 1).
    """
    cap = MAX_PRERENDER_PAGES if max_pages is None else max_pages
    is_pdf = image_bytes[:4] == b"%PDF"
    with tempfile.NamedTemporaryFile(suffix="-" + original_filename, delete=False) as inp:
        inp.write(image_bytes)
        inp_path = inp.name

    base_path: str | None = None
    rendered_paths: list[str] = []
    try:
        if not is_pdf:
            yield [inp_path], 1
            return
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as out:
            base_path = out.name
        with Document.open(inp_path) as doc:
            total_pages = doc.get_page_count()
            img = doc.get_settings().get_image_settings()
            img.set_export_format(ImageExportFormat.JPEG)
            img.set_jpeg_quality(_PRERENDER_JPEG_QUALITY)
            doc.export_as_image(base_path)
        # export_as_image() writes ALL pages; track them all for cleanup but
        # only hand back (and process) the first `cap`.
        rendered_paths = _collect_rendered_jpegs(base_path)
        yield rendered_paths[:cap], total_pages
    finally:
        # base_path is the empty temp NamedTemporaryFile created the name from;
        # a multi-page export leaves it unused, so clean it up alongside the
        # actual per-page JPEGs.
        for p in {inp_path, base_path, *rendered_paths}:
            if p and os.path.exists(p):
                os.unlink(p)


@contextlib.contextmanager
def _prepared_input(image_bytes: bytes, original_filename: str) -> Iterator[str]:
    """Single-page variant of _prepared_pages — the describe path is
    inherently per-image, so it processes page 1 only (documented)."""
    with _prepared_pages(image_bytes, original_filename, max_pages=1) as (paths, _total):
        yield paths[0]


def _build_ocr_code(filename: str, echo: dict, *, table_detection: bool) -> str:
    """The snippet the UI shows as 'how you'd do this yourself' for Adaptive OCR.

    Deliberately NOT the four obvious lines (open → set engine → extract). OCR is
    not one SDK call here: _prepared_pages rasterises PDFs to one JPEG per page
    and runs Vision per page, and every document this feature demos is a PDF. The
    short form would error on all four of them — worse than no Code view, in the
    one artefact built to prove the SDK works. So the snippet carries the
    pre-render, framed as what it is from the reader's side: Adaptive OCR reads
    page images.

    Mirrors _run_vision's getter style (doc.get_settings()) rather than
    _build_code's property style, because the getter path is the one proven to
    execute.

    `languages` and `table_detection` interpolate from the run that produced the
    result, so the snippet and the output on screen agree.

    The pages are exported into a tempfile.TemporaryDirectory, mirroring what
    _prepared_pages does with a NamedTemporaryFile basename. Fixed names in the
    CWD look tidier and are silently wrong: run the snippet on a 3-page PDF and
    then a 1-page PDF from the same directory, and run 2's glob still returns
    run 1's page-1..3.jpg, so `paths` is non-empty, the single-page fallback
    never fires, and the snippet OCRs the PREVIOUS document while printing it
    as the current one. Trying a second document is the first thing a prospect
    does. A private directory also means the glob cannot meet an unrelated
    page-cover.jpg, on which the numeric sort key raises AttributeError.
    """
    is_markdown = echo["outputFormat"] == "markdown"
    # One import per line: PEP 8, and this is pasted into a customer's project.
    # json is only needed by the merge, which the markdown branch does not do.
    # An unused import would be harmless but the snippet is read as much as run.
    stdlib = ["glob", "os", "re", "tempfile"]
    if not is_markdown:
        stdlib.insert(1, "json")
    # Trailing blank line: stdlib and third-party are separate import groups.
    imports = "".join(f"import {module}\n" for module in stdlib) + "\n"
    sdk_imports = (
        "from nutrient_sdk import (Document, ImageExportFormat, Vision,\n"
        "                          VisionEngine, VisionFeatures"
        + (", VisionOutputFormat)\n\n" if is_markdown else ")\n\n")
    )
    output_format_line = (
        "            vision.set_output_format(VisionOutputFormat.MARKDOWN)\n"
        if is_markdown
        else ""
    )
    if is_markdown:
        tail = f"print({PAGE_BREAK!r}.join(raws))\n"
    else:
        # The minimal merge: rewrite pageNumber/readingOrder and concatenate.
        # merge_element_pages also harvests page width/height from `metadata`,
        # which exists only to place overlay boxes — studio plumbing, not
        # something a reader of this snippet needs.
        tail = (
            "elements, next_order = [], 0\n"
            "for page_idx, raw in enumerate(raws, start=1):\n"
            "    payload = json.loads(raw)\n"
            '    page_elements = payload.get("elements", [])\n'
            '    page_elements.sort(key=lambda e: e.get("readingOrder", 0))\n'
            "    for element in page_elements:\n"
            "        # Each per-page call reports pageNumber=1 and restarts\n"
            "        # readingOrder at 0 — rewrite both or the pages interleave.\n"
            '        element["pageNumber"] = page_idx\n'
            '        element["readingOrder"] = next_order\n'
            "        next_order += 1\n"
            "        elements.append(element)\n\n"
            "print(json.dumps(elements, indent=2))\n"
        )
    # json.dumps, not an f-string in quotes: a filename is user-supplied and one
    # embedded quote or backslash would break the literal.
    #
    # `languages` a few lines down is interpolated raw instead, and that
    # asymmetry is deliberate. It is safe BY ALLOWLIST, not by escaping:
    # validate_ocr_options() checks every '+'-separated code against
    # OCR_LANGUAGES before `echo` exists, so the value here can only ever be
    # allowlisted codes joined with '+'. Do not "fix" it into json.dumps —
    # set_default_languages() takes a bare string and the quotes are already
    # in the template.
    open_target = json.dumps(filename)
    return (
        imports
        + sdk_imports
        + "# Adaptive OCR reads page images, so render each PDF page to a JPEG\n"
        "# first. export_as_image() does the whole document in one call.\n"
        "# The pages go to a private temporary directory, so the glob below can\n"
        "# only ever match this run's own output — point the snippet at a second\n"
        "# document and it cannot pick up the first one's pages — and nothing is\n"
        "# left behind in your working directory.\n"
        "with tempfile.TemporaryDirectory() as pages_dir:\n"
        '    base = os.path.join(pages_dir, "page.jpg")\n'
        f"    with Document.open({open_target}) as document:\n"
        "        images = document.get_settings().get_image_settings()\n"
        "        images.set_export_format(ImageExportFormat.JPEG)\n"
        "        document.export_as_image(base)\n\n"
        "    # Multi-page writes page-1.jpg, page-2.jpg, …; a single-page\n"
        "    # document is written to page.jpg itself, which is why the glob\n"
        "    # needs the `base` fallback. Sort numerically so 10 follows 9.\n"
        '    paths = sorted(glob.glob(os.path.join(pages_dir, "page-*.jpg")),\n'
        '                   key=lambda p: int(re.search(r"-(\\d+)\\.jpg$", p).group(1)))\n'
        "    paths = paths or [base]\n\n"
        "    # Still inside the with: the JPEGs are deleted when it exits, so\n"
        "    # every page has to be read before then.\n"
        "    raws = []\n"
        "    for path in paths:\n"
        "        with Document.open(path) as page:\n"
        "            settings = page.get_settings()\n"
        "            vision = settings.get_vision_settings()\n"
        "            vision.set_engine(VisionEngine.ADAPTIVE_OCR)\n"
        "            vision.set_features(VisionFeatures.ALL.value)\n"
        + output_format_line
        + f'            settings.get_ocr_settings().set_default_languages("{echo["languages"]}")\n'
        f"            settings.get_ocr_settings().set_enable_table_detection({table_detection})\n"
        "            raws.append(Vision.set(page).extract_content())\n\n"
        + tail
    )


def _build_describe_code(
    filename: str,
    *,
    is_pdf: bool,
    prompt: str | None,
    level: str,
    provider: str,
) -> str:
    """The 'how you'd do this yourself' snippet for Image description.

    PAGE 1 ONLY, and the snippet says so. describe_image wraps _prepared_input,
    which is the max_pages=1 variant — the describe path is inherently per-image.
    A snippet that looked like it covered a whole document would be a lie a
    prospect pastes into their own project.

    Takes `is_pdf` rather than inferring from the extension, because
    _prepared_pages branches on the magic bytes. _build_ocr_code receives only
    `filename` and so emits a rasterisation that never happened for image input;
    do not reproduce that here.

    `prompt` is USER-SUPPLIED and is json.dumps-escaped. The allowlist argument
    that lets _build_ocr_code interpolate `languages` raw does not apply.
    """
    open_target = json.dumps(filename)
    level_const = "DETAILED" if level.lower() == "detailed" else "STANDARD"
    is_openai = provider.lower() == "openai"
    provider_const = "OPEN_AI" if is_openai else "CLAUDE"
    key_env = "OPENAI_API_KEY" if is_openai else "ANTHROPIC_API_KEY"
    key_setter = (
        "settings.get_open_ai_api_endpoint_settings()"
        if is_openai
        else "settings.get_claude_api_settings()"
    )

    # Per-branch, because only the PDF path uses ImageExportFormat and tempfile.
    # Verified 2026-08-11: DescriptionLevel, Document, ImageExportFormat and
    # Vision are all top-level `from nutrient_sdk import (...)` names, while
    # VlmProvider lives in nutrient_sdk.vlmprovider — the service imports it
    # separately for exactly that reason. Do NOT emit an import the snippet does
    # not use: unbound_names() will not catch it, but the snippet is read as much
    # as run, and a stray name invites a reader to wonder what it is for.
    if is_pdf:
        imports = (
            "import glob\n"
            "import os\n"
            "import re\n"
            "import tempfile\n\n"
            "from nutrient_sdk import (DescriptionLevel, Document,\n"
            "                          ImageExportFormat, Vision)\n"
            "from nutrient_sdk.vlmprovider import VlmProvider\n\n"
        )
    else:
        imports = (
            "import os\n\n"
            "from nutrient_sdk import DescriptionLevel, Document, Vision\n"
            "from nutrient_sdk.vlmprovider import VlmProvider\n\n"
        )

    prompt_line = (
        f"    descriptor.set_standard_prompt({json.dumps(prompt)})\n" if prompt else ""
    )

    body = (
        "    settings = page.get_settings()\n"
        "    descriptor = settings.get_vision_descriptor_settings()\n"
        f"    descriptor.set_level(DescriptionLevel.{level_const})\n"
        + prompt_line
        + f"    settings.get_vision_settings().set_provider(VlmProvider.{provider_const})\n"
        f'    {key_setter}.set_api_key(os.environ["{key_env}"])\n\n'
        "    print(Vision.set(page).describe())\n"
    )

    if not is_pdf:
        # No pre-render: _prepared_pages yields a non-PDF unchanged, so the
        # snippet must not claim to rasterise anything.
        return (
            imports
            + "# An image is already a page, so there is nothing to rasterise.\n"
            "# Vision.describe() looks at ONE page image and returns prose.\n"
            f"with Document.open({open_target}) as page:\n" + body
        )

    # Written out as its own plainly-indented literal (8-space body) rather
    # than re-indenting `body` with a `.replace()` chain: that chain is fragile
    # — it can silently mangle a line that happens to start with more than one
    # run of 4 spaces — and correctness beats DRY here. Keep this in sync with
    # `body` above by hand if either changes.
    nested_prompt_line = (
        f"        descriptor.set_standard_prompt({json.dumps(prompt)})\n" if prompt else ""
    )
    nested_body = (
        "        settings = page.get_settings()\n"
        "        descriptor = settings.get_vision_descriptor_settings()\n"
        f"        descriptor.set_level(DescriptionLevel.{level_const})\n"
        + nested_prompt_line
        + f"        settings.get_vision_settings().set_provider(VlmProvider.{provider_const})\n"
        f'        {key_setter}.set_api_key(os.environ["{key_env}"])\n\n'
        "        print(Vision.set(page).describe())\n"
    )

    # export_as_image() rasterises EVERY page in one call — a multi-page PDF is
    # written as page-1.jpg, page-2.jpg, ... and the bare `base` path is never
    # created; only a single-page document writes directly to `base`. Opening
    # a hardcoded "page-1.jpg" (or `base` unconditionally) raises
    # FileNotFoundError on any real multi-page PDF — glob for the suffixed
    # outputs, sort numerically, and fall back to `base` for the single-page
    # case, exactly as _build_ocr_code does. Vision.describe() is per-image,
    # so only the first path is opened.
    return (
        imports
        + "# Vision.describe() reads ONE page image, so this path handles PAGE 1\n"
        "# ONLY — it is not a whole-document summary. export_as_image()\n"
        "# rasterises EVERY page in one call; this snippet uses only the first\n"
        "# one. The pages go to a private temporary directory, so nothing is\n"
        "# left in your working directory and a second run cannot pick up the\n"
        "# first run's output.\n"
        "with tempfile.TemporaryDirectory() as pages_dir:\n"
        '    base = os.path.join(pages_dir, "page.jpg")\n'
        f"    with Document.open({open_target}) as document:\n"
        "        images = document.get_settings().get_image_settings()\n"
        "        images.set_export_format(ImageExportFormat.JPEG)\n"
        "        document.export_as_image(base)\n\n"
        "    # Multi-page writes page-1.jpg, page-2.jpg, …; a single-page\n"
        "    # document is written to page.jpg itself, which is why the glob\n"
        "    # needs the `base` fallback. Sort numerically so 10 follows 9.\n"
        '    paths = sorted(glob.glob(os.path.join(pages_dir, "page-*.jpg")),\n'
        '                   key=lambda p: int(re.search(r"-(\\d+)\\.jpg$", p).group(1)))\n'
        "    paths = paths or [base]\n\n"
        "    # Still inside the with: the JPEG is deleted when it exits. Only\n"
        "    # the first page is opened — this endpoint is page 1 only.\n"
        "    with Document.open(paths[0]) as page:\n"
        + nested_body
    )


def _build_handwriting_code(
    filename: str, *, engine: str, provider: str | None
) -> str:
    """The 'how you'd do this yourself' snippet for handwriting recognition.

    Same shape as _build_ocr_code's JSON branch and for the same reason: neither
    ICR nor VLM_ENHANCED_ICR is one SDK call here, because _prepared_pages
    rasterises a PDF to one JPEG per page and runs Vision per page. Two of the
    four handwriting documents are JPEGs already, but the snippet has to work on
    either, and the glob-with-base-fallback covers both.

    No OCR settings lines: set_default_languages() and
    set_enable_table_detection() belong to Adaptive OCR's panel, and neither
    endpoint accepts them.

    The provider block appears only on the VLM branch. Local ICR's claim is that
    nothing leaves the machine, and a snippet that reads an API key would
    contradict the feature it is demonstrating.

    Pages go into a tempfile.TemporaryDirectory for the reason spelled out at
    length in _build_ocr_code: fixed names in the CWD make run 2 read run 1's
    pages, silently, at exit code 0.
    """
    is_vlm = engine == "VLM"
    engine_constant = "VisionEngine.VLM_ENHANCED_ICR" if is_vlm else "VisionEngine.ICR"
    # One blank line between the stdlib group and the nutrient_sdk group, on
    # both branches — matching _build_ocr_code's imports exactly.
    imports = "import glob\nimport json\nimport os\nimport re\nimport tempfile\n\n"
    sdk_imports = (
        "from nutrient_sdk import (Document, ImageExportFormat, Vision,\n"
        "                          VisionEngine, VisionFeatures)\n"
    )
    # Gated on `provider` too, not just `is_vlm`: with no provider configured
    # (the /vlm default — see _run_vision's `if provider:` guard, which talks
    # to a local VLM server and sets no provider at all), nothing below
    # references VlmProvider, and an unused import is a defect in a snippet
    # meant to be read as much as run.
    if is_vlm and provider:
        sdk_imports += "from nutrient_sdk.vlmprovider import VlmProvider\n"
    sdk_imports += "\n"

    if is_vlm and provider == "openai":
        provider_lines = (
            "            vision.set_provider(VlmProvider.OPEN_AI)\n"
            '            settings.get_open_ai_api_endpoint_settings().set_api_key(\n'
            '                os.environ["OPENAI_API_KEY"])\n'
        )
    elif is_vlm and provider:
        provider_lines = (
            "            vision.set_provider(VlmProvider.CLAUDE)\n"
            "            settings.get_claude_api_settings().set_api_key(\n"
            '                os.environ["ANTHROPIC_API_KEY"])\n'
        )
    elif is_vlm:
        # provider=None mirrors _run_vision's `if provider:` guard: /vlm's
        # own default (no provider set) talks to a local VLM server at
        # localhost:1234, not Claude — a snippet that set Claude here would
        # not match the run that produced it, and would fail without
        # ANTHROPIC_API_KEY for a reader who never configured a provider.
        provider_lines = (
            "            # No provider set: the SDK default talks to a local VLM\n"
            "            # server at localhost:1234 (e.g. LM Studio or Ollama).\n"
        )
    else:
        provider_lines = ""

    lead = (
        "# Handwriting recognition reads page images, so render each PDF page to\n"
        "# a JPEG first. export_as_image() does the whole document in one call,\n"
        "# and an image input passes straight through.\n"
        "# The pages go to a private temporary directory, so the glob below can\n"
        "# only ever match this run's own output.\n"
    )
    # json.dumps, not an f-string in quotes: a filename is user-supplied and one
    # embedded quote or backslash would break the literal.
    open_target = json.dumps(filename)
    return (
        imports
        + sdk_imports
        + lead
        + "with tempfile.TemporaryDirectory() as pages_dir:\n"
        '    base = os.path.join(pages_dir, "page.jpg")\n'
        f"    with Document.open({open_target}) as document:\n"
        "        images = document.get_settings().get_image_settings()\n"
        "        images.set_export_format(ImageExportFormat.JPEG)\n"
        "        document.export_as_image(base)\n\n"
        "    # Multi-page writes page-1.jpg, page-2.jpg, …; a single-page\n"
        "    # document is written to page.jpg itself, which is why the glob\n"
        "    # needs the `base` fallback. Sort numerically so 10 follows 9.\n"
        '    paths = sorted(glob.glob(os.path.join(pages_dir, "page-*.jpg")),\n'
        '                   key=lambda p: int(re.search(r"-(\\d+)\\.jpg$", p).group(1)))\n'
        "    paths = paths or [base]\n\n"
        "    # Still inside the with: the JPEGs are deleted when it exits, so\n"
        "    # every page has to be read before then.\n"
        "    raws = []\n"
        "    for path in paths:\n"
        "        with Document.open(path) as page:\n"
        "            settings = page.get_settings()\n"
        "            vision = settings.get_vision_settings()\n"
        f"            vision.set_engine({engine_constant})\n"
        "            vision.set_features(VisionFeatures.ALL.value)\n"
        + provider_lines
        + "            raws.append(Vision.set(page).extract_content())\n\n"
        "elements, next_order = [], 0\n"
        "for page_idx, raw in enumerate(raws, start=1):\n"
        "    payload = json.loads(raw)\n"
        '    page_elements = payload.get("elements", [])\n'
        '    page_elements.sort(key=lambda e: e.get("readingOrder", 0))\n'
        "    for element in page_elements:\n"
        "        # Each per-page call reports pageNumber=1 and restarts\n"
        "        # readingOrder at 0 — rewrite both or the pages interleave.\n"
        '        element["pageNumber"] = page_idx\n'
        '        element["readingOrder"] = next_order\n'
        "        next_order += 1\n"
        "        elements.append(element)\n\n"
        "print(json.dumps(elements, indent=2))\n"
    )


def _build_tables_code(filename: str, *, is_pdf: bool) -> str:
    """The 'how you'd do this yourself' snippet for Table Extraction.

    Takes `is_pdf` rather than inferring from the extension, because
    _prepared_pages branches on the magic bytes (image_bytes[:4] == b"%PDF"),
    not the name. _build_ocr_code receives only `filename` and so cannot make
    that distinction: POST a PNG to /ocr and its snippet describes a
    rasterisation that never happened. Passing the flag is the fix.

    The PDF branch carries the pre-render for the same reason _build_ocr_code
    does — Vision runs per page image, and every document this feature demos is
    a PDF, so the obvious short form would error on all of them.

    `VisionEngine.VLM_ENHANCED_ICR` is deliberate, not `VisionEngine.VLM`:
    extract_tables passes the engine STRING "VLM", which _run_vision's
    engine_map translates to VLM_ENHANCED_ICR, and VisionEngine.VLM does not
    exist on this SDK build (only ADAPTIVE_OCR, ICR, VLM_ENHANCED_ICR). This
    snippet emitted the nonexistent name until 2026-08-13, so anyone who copied
    it hit an AttributeError on the line doing the actual work. Every other
    guard in tests/test_extraction_code.py passed it, because `VisionEngine` is
    a bound NAME and only the ATTRIBUTE was wrong; there is now a test that
    walks each snippet's attribute access against the real enums.

    Pages go into a tempfile.TemporaryDirectory the snippet owns. Fixed names in
    the CWD look tidier and are silently wrong: run it on a 3-page PDF then a
    1-page PDF from the same directory, and run 2's glob still returns run 1's
    page-1..3.jpg, so `paths` is non-empty, the single-page fallback never
    fires, and it prints the PREVIOUS document's tables as the current one.
    """
    # json.dumps, not an f-string in quotes: a filename is user-supplied and one
    # embedded quote or backslash would break the literal.
    open_target = json.dumps(filename)

    # The table filter and the print are shared by both branches — the only
    # difference is how `raws` gets populated.
    tail = (
        "tables = []\n"
        "for page_idx, raw in enumerate(raws, start=1):\n"
        '    for element in json.loads(raw).get("elements", []):\n'
        '        if str(element.get("type", "")).lower() == "table":\n'
        '            element["pageNumber"] = page_idx\n'
        "            tables.append(element)\n\n"
        'print(f"{len(tables)} tables")\n'
        "print(json.dumps(tables, indent=2))\n"
    )

    # 12-space indent: nested inside `for path in paths:` (4) -> `with
    # Document.open(path) as page:` (8) -> this body (12), matching the
    # working pattern in _build_ocr_code above.
    vision_block = (
        "            settings = page.get_settings()\n"
        "            vision = settings.get_vision_settings()\n"
        "            vision.set_engine(VisionEngine.VLM_ENHANCED_ICR)\n"
        "            # VisionFeatures.ALL rather than a TABLE-specific flag: the\n"
        "            # narrower features are a no-op (NAPY-20), so ask for\n"
        "            # everything and filter the elements afterwards.\n"
        "            vision.set_features(VisionFeatures.ALL.value)\n"
        "            raws.append(Vision.set(page).extract_content())\n\n"
    )

    if not is_pdf:
        # No pre-render: _prepared_pages yields the input unchanged for a
        # non-PDF, so the snippet must not claim to rasterise anything.
        # Written out as its own 4-space-indented literal rather than
        # re-indenting the 8-space `vision_block` above: a string.replace()
        # chain doing that re-indentation is fragile and not worth the DRY.
        non_pdf_vision_block = (
            "    settings = page.get_settings()\n"
            "    vision = settings.get_vision_settings()\n"
            "    vision.set_engine(VisionEngine.VLM_ENHANCED_ICR)\n"
            "    # VisionFeatures.ALL rather than a TABLE-specific flag: the\n"
            "    # narrower features are a no-op (NAPY-20), so ask for\n"
            "    # everything and filter the elements afterwards.\n"
            "    vision.set_features(VisionFeatures.ALL.value)\n"
            "    raws.append(Vision.set(page).extract_content())\n\n"
        )
        return (
            "import json\n\n"
            "from nutrient_sdk import Document, Vision, VisionEngine, VisionFeatures\n\n"
            "# An image is already a page, so there is nothing to rasterise.\n"
            "raws = []\n"
            f"with Document.open({open_target}) as page:\n"
            + non_pdf_vision_block
            + tail
        )

    return (
        "import glob\n"
        "import json\n"
        "import os\n"
        "import re\n"
        "import tempfile\n\n"
        "from nutrient_sdk import (Document, ImageExportFormat, Vision,\n"
        "                          VisionEngine, VisionFeatures)\n\n"
        "# Table extraction reads page images, so render each PDF page to a JPEG\n"
        "# first. export_as_image() does the whole document in one call.\n"
        "# The pages go to a private temporary directory, so the glob below can\n"
        "# only ever match this run's own output — point the snippet at a second\n"
        "# document and it cannot pick up the first one's pages — and nothing is\n"
        "# left behind in your working directory.\n"
        "with tempfile.TemporaryDirectory() as pages_dir:\n"
        '    base = os.path.join(pages_dir, "page.jpg")\n'
        f"    with Document.open({open_target}) as document:\n"
        "        images = document.get_settings().get_image_settings()\n"
        "        images.set_export_format(ImageExportFormat.JPEG)\n"
        "        document.export_as_image(base)\n\n"
        "    # Multi-page writes page-1.jpg, page-2.jpg, …; a single-page\n"
        "    # document is written to page.jpg itself, which is why the glob\n"
        "    # needs the `base` fallback. Sort numerically so 10 follows 9.\n"
        '    paths = sorted(glob.glob(os.path.join(pages_dir, "page-*.jpg")),\n'
        '                   key=lambda p: int(re.search(r"-(\\d+)\\.jpg$", p).group(1)))\n'
        "    paths = paths or [base]\n"
        "    # The studio stops at the first 10 pages (MAX_PRERENDER_PAGES) and\n"
        "    # reports how many it processed. Drop this slice to do the whole\n"
        "    # document — but then a long PDF yields more than the panel showed.\n"
        "    paths = paths[:10]\n\n"
        "    # Still inside the with: the JPEGs are deleted when it exits, so\n"
        "    # every page has to be read before then.\n"
        "    raws = []\n"
        "    for path in paths:\n"
        "        with Document.open(path) as page:\n"
        + vision_block
        + tail
    )


def _build_markdown_code(filename: str, *, is_pdf: bool, provider: str) -> str:
    """The 'how you'd do this yourself' snippet for Markdown export.

    Same shape as _build_tables_code: extract_markdown also calls
    _run_with_prerender(..., "VLM", ...), so the same PDF/image split and the
    same MAX_PRERENDER_PAGES cap apply. It differs from _build_tables_code in
    two ways that matter: it sets VisionOutputFormat.MARKDOWN (so Vision
    returns page text, not an elements JSON graph, and there is nothing to
    filter afterwards), and it always configures a provider — extract_markdown
    defaults `provider` to "claude" and passes it straight through, unlike
    /vlm's handwriting path where an unset provider is itself a valid,
    documented local-server mode. So the provider block here is unconditional,
    matching _build_describe_code's always-on provider rather than
    _build_handwriting_code's optional one.

    `VisionEngine.VLM_ENHANCED_ICR` is deliberate, not `VisionEngine.VLM`:
    _run_vision's engine_map sends the "VLM" string _run_with_prerender is
    called with to VLM_ENHANCED_ICR, and VisionEngine.VLM does not exist on
    this SDK build. Pin the constant that actually runs.

    Multi-page output is joined with PAGE_BREAK, the same separator
    merge_markdown_pages uses, so a prospect who runs this against a
    multi-page PDF sees the same page breaks the studio showed them.

    Pages go into a tempfile.TemporaryDirectory for the reason spelled out at
    length in _build_ocr_code and _build_tables_code: fixed names in the CWD
    make run 2 silently read run 1's pages, at exit code 0.
    """
    is_openai = provider.lower() == "openai"
    provider_const = "OPEN_AI" if is_openai else "CLAUDE"
    key_env = "OPENAI_API_KEY" if is_openai else "ANTHROPIC_API_KEY"
    key_setter = (
        "settings.get_open_ai_api_endpoint_settings()"
        if is_openai
        else "settings.get_claude_api_settings()"
    )

    # json.dumps, not an f-string in quotes: a filename is user-supplied and one
    # embedded quote or backslash would break the literal.
    open_target = json.dumps(filename)

    # PDF branch: 12-space indent (for path in paths: -> with Document.open -> body),
    # matching _build_handwriting_code's VLM provider block exactly.
    if not is_openai:
        provider_lines = (
            "            vision.set_provider(VlmProvider.CLAUDE)\n"
            f'            settings.get_claude_api_settings().set_api_key(\n'
            f'                os.environ["{key_env}"])\n'
        )
    else:
        provider_lines = (
            "            vision.set_provider(VlmProvider.OPEN_AI)\n"
            f'            settings.get_open_ai_api_endpoint_settings().set_api_key(\n'
            f'                os.environ["{key_env}"])\n'
        )

    if not is_pdf:
        # No pre-render: _prepared_pages yields the input unchanged for a
        # non-PDF, so the snippet must not claim to rasterise anything.
        non_pdf_provider_lines = (
            f"    vision.set_provider(VlmProvider.{provider_const})\n"
            f'    {key_setter}.set_api_key(os.environ["{key_env}"])\n'
        )
        return (
            "import os\n\n"
            "from nutrient_sdk import (Document, Vision, VisionEngine,\n"
            "                          VisionFeatures, VisionOutputFormat)\n"
            "from nutrient_sdk.vlmprovider import VlmProvider\n\n"
            "# An image is already a page, so there is nothing to rasterise.\n"
            f"with Document.open({open_target}) as page:\n"
            "    settings = page.get_settings()\n"
            "    vision = settings.get_vision_settings()\n"
            "    vision.set_engine(VisionEngine.VLM_ENHANCED_ICR)\n"
            "    vision.set_features(VisionFeatures.ALL.value)\n"
            "    vision.set_output_format(VisionOutputFormat.MARKDOWN)\n"
            + non_pdf_provider_lines
            + "\n"
            "    print(Vision.set(page).extract_content())\n"
        )

    return (
        "import glob\n"
        "import os\n"
        "import re\n"
        "import tempfile\n\n"
        "from nutrient_sdk import (Document, ImageExportFormat, Vision,\n"
        "                          VisionEngine, VisionFeatures,\n"
        "                          VisionOutputFormat)\n"
        "from nutrient_sdk.vlmprovider import VlmProvider\n\n"
        "# Markdown export reads page images, so render each PDF page to a JPEG\n"
        "# first. export_as_image() does the whole document in one call.\n"
        "# The pages go to a private temporary directory, so the glob below can\n"
        "# only ever match this run's own output — point the snippet at a second\n"
        "# document and it cannot pick up the first one's pages — and nothing is\n"
        "# left behind in your working directory.\n"
        "with tempfile.TemporaryDirectory() as pages_dir:\n"
        '    base = os.path.join(pages_dir, "page.jpg")\n'
        f"    with Document.open({open_target}) as document:\n"
        "        images = document.get_settings().get_image_settings()\n"
        "        images.set_export_format(ImageExportFormat.JPEG)\n"
        "        document.export_as_image(base)\n\n"
        "    # Multi-page writes page-1.jpg, page-2.jpg, …; a single-page\n"
        "    # document is written to page.jpg itself, which is why the glob\n"
        "    # needs the `base` fallback. Sort numerically so 10 follows 9.\n"
        '    paths = sorted(glob.glob(os.path.join(pages_dir, "page-*.jpg")),\n'
        '                   key=lambda p: int(re.search(r"-(\\d+)\\.jpg$", p).group(1)))\n'
        "    paths = paths or [base]\n"
        "    # The studio stops at the first 10 pages (MAX_PRERENDER_PAGES) and\n"
        "    # reports how many it processed. Drop this slice to do the whole\n"
        "    # document — but then a long PDF yields more than the panel showed.\n"
        "    paths = paths[:10]\n\n"
        "    # Still inside the with: the JPEGs are deleted when it exits, so\n"
        "    # every page has to be read before then.\n"
        "    raws = []\n"
        "    for path in paths:\n"
        "        with Document.open(path) as page:\n"
        "            settings = page.get_settings()\n"
        "            vision = settings.get_vision_settings()\n"
        "            vision.set_engine(VisionEngine.VLM_ENHANCED_ICR)\n"
        "            vision.set_features(VisionFeatures.ALL.value)\n"
        "            vision.set_output_format(VisionOutputFormat.MARKDOWN)\n"
        + provider_lines
        + "            raws.append(Vision.set(page).extract_content())\n\n"
        f"print({PAGE_BREAK!r}.join(raws))\n"
    )


def _build_text_code(filename: str) -> str:
    """The Text export snippet — genuinely one SDK call, unlike its siblings.

    Every other builder in this module describes a pre-render loop, because
    Vision needs rasterized pages (NAPY-7/NAPY-8). export_as_text() reads the
    text layer the document already carries, so there is no loop, no engine
    constant and no provider. Saying otherwise would misdescribe the run.

    The TemporaryDirectory is load-bearing, not tidiness: export_as_text()
    overwrites whatever path it is given, and the OCR snippet shipped a version
    writing fixed names into the working directory, where stale files from a
    previous run were silently read back as the current document's output.
    """
    return (
        "# Text export — the plain text the document already carries.\n"
        "#\n"
        "# One SDK call: no model, no API key, no network. A scanned page has\n"
        "# no text layer, so this writes an EMPTY file rather than raising —\n"
        "# that is the signal to run OCR instead, not an error.\n"
        "import os\n"
        "import tempfile\n\n"
        "from nutrient_sdk import Document, License\n\n"
        'License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])\n\n'
        "# A directory this snippet owns: export_as_text() overwrites whatever\n"
        "# path it is handed, so a fixed name would collide across runs.\n"
        "with tempfile.TemporaryDirectory() as out_dir:\n"
        '    out_path = os.path.join(out_dir, "text.txt")\n'
        f"    with Document.open({filename!r}) as doc:\n"
        "        page_count = doc.get_page_count()\n"
        "        doc.export_as_text(out_path)\n"
        "    # Read inside the block — the file is gone once it exits.\n"
        '    with open(out_path, encoding="utf-8") as fh:\n'
        "        text = fh.read()\n\n"
        'print(f"{page_count} pages, {len(text)} characters")\n'
        "print(text)\n"
    )


def extract_text_ocr(
    image_bytes: bytes,
    original_filename: str,
    *,
    languages: str = "eng",
    table_detection: bool = True,
    output_format: str = "json",
) -> dict:
    """Adaptive OCR. Runs entirely locally — no provider, no API key, no network.

    Returns the SAME key set regardless of output_format. The markdown branch
    used to omit statistics/textElements/fullText/pages/rawElements entirely,
    which crashed the studio's results panel (it reads
    result.textElements.length unconditionally) — /structured never does this;
    it always returns a complete Envelope regardless of options, and this
    follows that model. `engine` is "OCR" on both branches too: the markdown
    branch used to say "ADAPTIVE_OCR", but tests/test_extraction.py pins "OCR"
    for this endpoint.
    """
    import time

    from app.services.ocr_options import validate_ocr_options

    echo = validate_ocr_options(languages, output_format)
    start = time.perf_counter()
    if echo["outputFormat"] == "markdown":
        md, total_pages, processed_pages = _run_with_prerender(
            image_bytes,
            original_filename,
            "OCR",
            output_format=VisionOutputFormat.MARKDOWN,
            languages=languages,
            table_detection=table_detection,
        )
        result: dict = {
            "engine": "OCR",
            "filename": original_filename,
            "statistics": {
                "totalElements": 0,
                "textElements": 0,
                "averageConfidence": 0,
                "lowConfidenceElements": 0,
            },
            "fullText": "",
            "textElements": [],
            "rawElements": [],
            "pages": [],
            "markdown": md,
            "totalPages": total_pages,
            "processedPages": processed_pages,
        }
    else:
        result = _extract_with_engine(
            image_bytes,
            original_filename,
            "OCR",
            languages=languages,
            table_detection=table_detection,
        )
        result["markdown"] = ""
    result["config"] = {**echo, "tableDetection": table_detection}
    # After config, on the shared path, so both branches return the same key set —
    # test_ocr_endpoint_markdown_key_set_matches_json is what enforces that.
    result["code"] = _build_ocr_code(
        original_filename, echo, table_detection=table_detection
    )
    result["timingMs"] = int((time.perf_counter() - start) * 1000)
    return result


def _extract_handwriting(
    image_bytes: bytes,
    original_filename: str,
    engine: str,
    *,
    provider: str | None,
) -> dict:
    """Shared tail for the two handwriting engines.

    They differ only by VisionEngine constant and, for VLM, a provider — so the
    three keys the studio's panel needs (`code`, `timingMs`, `config`) are added
    in one place rather than in two copies that would drift. `/ocr` grew the
    same three keys separately and keeps its own copy, because it also has a
    markdown branch and an options echo neither of these has.
    """
    import time

    start = time.perf_counter()
    result = _extract_with_engine(
        image_bytes, original_filename, engine, provider=provider
    )
    result["config"] = {"engine": engine}
    if provider:
        result["config"]["provider"] = provider
    result["code"] = _build_handwriting_code(
        original_filename, engine=engine, provider=provider
    )
    result["timingMs"] = int((time.perf_counter() - start) * 1000)
    return result


def extract_text_icr(image_bytes: bytes, original_filename: str) -> dict:
    return _extract_handwriting(image_bytes, original_filename, "ICR", provider=None)


def extract_text_vlm(
    image_bytes: bytes, original_filename: str, provider: str | None = None
) -> dict:
    return _extract_handwriting(
        image_bytes, original_filename, "VLM", provider=provider
    )


def describe_image(
    image_bytes: bytes,
    original_filename: str,
    *,
    prompt: str | None = None,
    provider: str = "claude",
    level: str = "standard",
) -> dict:
    """Run Vision.describe() with an optional custom prompt, provider, and detail level."""
    import time

    from nutrient_sdk.vlmprovider import VlmProvider

    start = time.perf_counter()
    level_map = {
        "standard": DescriptionLevel.STANDARD,
        "detailed": DescriptionLevel.DETAILED,
    }
    level_key = level.lower()
    if level_key not in level_map:
        raise ValueError(f"Unsupported level: {level}")

    with _prepared_input(image_bytes, original_filename) as path:
        with Document.open(path) as doc:
            s = doc.get_settings()
            s.get_vision_descriptor_settings().set_level(level_map[level_key])
            if prompt:
                s.get_vision_descriptor_settings().set_standard_prompt(prompt)
            p = provider.lower()
            if p == "claude":
                s.get_vision_settings().set_provider(VlmProvider.CLAUDE)
                s.get_claude_api_settings().set_api_key(os.environ["ANTHROPIC_API_KEY"])
            elif p == "openai":
                s.get_vision_settings().set_provider(VlmProvider.OPEN_AI)
                s.get_open_ai_api_endpoint_settings().set_api_key(os.environ["OPENAI_API_KEY"])
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            vision = Vision.set(doc)
            text = vision.describe()

    return {
        "engine": "VLM_DESCRIBE",
        "filename": original_filename,
        "provider": p,
        "level": level_key,
        "promptUsed": prompt or "(default)",
        "text": text,
        # Same magic-byte test _prepared_pages uses, so the snippet describes the
        # path that actually ran rather than guessing from the extension.
        "code": _build_describe_code(
            original_filename,
            is_pdf=image_bytes[:4] == b"%PDF",
            prompt=prompt,
            level=level_key,
            provider=p,
        ),
        # /describe was the only extraction endpoint without this, and the
        # studio's meta row shows elapsed time for every other feature.
        "timingMs": int((time.perf_counter() - start) * 1000),
    }


def _format_tables(merged: dict, filename: str, provider: str) -> dict:
    elements = merged.get("elements", [])
    tables = [e for e in elements if str(e.get("type", "")).lower() == "table"]
    # Raster px dims per 1-based page, harvested by merge_element_pages from the
    # SDK's top-level `metadata`. Without these a raw bbox cannot be normalised.
    page_dims = {
        p["page"]: (p["width"], p["height"])
        for p in merged.get("pages", []) or []
        if p.get("width") and p.get("height")
    }

    def cell_citation(cell: dict, page_1: int | None) -> dict | None:
        """Fractional, 0-based-page citation — the same shape /structured and
        /ocr return, which is what lets the studio's overlay draw these with no
        new drawing code. Raw `bounds` are absolute raster pixels and stay in
        the payload alongside this, exactly as the OCR path keeps both."""
        bounds = cell.get("bounds")
        if not bounds or page_1 not in page_dims:
            return None
        w, h = page_dims[page_1]
        return {"page": page_1 - 1, **normalize_bbox(bounds, w, h)}

    return {
        "engine": "VLM_TABLES",
        "filename": filename,
        "provider": provider,
        "tableCount": len(tables),
        # Same array the OCR path returns, for the same reason: a consumer that
        # wants to place anything itself needs the page dimensions.
        "pages": merged.get("pages", []),
        "tables": [
            {
                # 0-based, matching the viewer and `citation.page`. The SDK
                # reports 1-based via merge_element_pages.
                "page": (t.get("pageNumber") - 1)
                if isinstance(t.get("pageNumber"), int)
                else None,
                "rowCount": t.get("rowCount"),
                "columnCount": t.get("columnCount"),
                "cells": [
                    {
                        "row": c.get("row"),
                        "column": c.get("column"),
                        "rowSpan": c.get("rowSpan"),
                        "colSpan": c.get("colSpan"),
                        "text": c.get("text"),
                        "confidence": round(c.get("confidence") or 0, 2),
                        "bounds": c.get("bounds"),
                        "citation": cell_citation(c, t.get("pageNumber")),
                    }
                    for c in t.get("cells", [])
                ],
            }
            for t in tables
        ],
        "rawElements": elements,
    }


def extract_tables(image_bytes: bytes, original_filename: str, provider: str = "claude") -> dict:
    merged, total_pages, processed_pages = _run_with_prerender(
        image_bytes,
        original_filename,
        "VLM",
        provider=provider,
        features=_DOCGRAPH_FEATURES,  # NAPY-20 workaround; _format_tables filters to table elements
    )
    result = _format_tables(merged, original_filename, provider)
    result["totalPages"] = total_pages
    result["processedPages"] = processed_pages
    # Same magic-byte test _prepared_pages uses, so the snippet describes the
    # path that actually ran rather than guessing from the extension.
    result["code"] = _build_tables_code(
        original_filename, is_pdf=image_bytes[:4] == b"%PDF"
    )
    return result


def extract_markdown(image_bytes: bytes, original_filename: str, provider: str = "claude") -> dict:
    # SDK returns Markdown text directly when output_format=MARKDOWN (not JSON);
    # multi-page output is joined with PAGE_BREAK separators.
    import time

    start = time.perf_counter()
    md, total_pages, processed_pages = _run_with_prerender(
        image_bytes,
        original_filename,
        "VLM",
        provider=provider,
        output_format=VisionOutputFormat.MARKDOWN,
    )
    result = {
        "engine": "VLM_MARKDOWN",
        "filename": original_filename,
        "provider": provider,
        "markdown": md,
        "charCount": len(md),
        "totalPages": total_pages,
        "processedPages": processed_pages,
    }
    # Same magic-byte test _prepared_pages uses, so the snippet describes the
    # path that actually ran rather than guessing from the extension.
    result["code"] = _build_markdown_code(
        original_filename, is_pdf=image_bytes[:4] == b"%PDF", provider=provider
    )
    result["timingMs"] = int((time.perf_counter() - start) * 1000)
    return result


def extract_text_export(image_bytes: bytes, original_filename: str) -> dict:
    """Plain text from the document's own text layer — export_as_text().

    Deliberately NOT _prepared_pages. That helper rasterizes PDFs to per-page
    JPEGs because Vision needs images; this call needs the opposite, the text
    the document already carries. So: no provider, no network, no model, and no
    MAX_PRERENDER_PAGES cap — the whole document, in milliseconds.

    A document with no text layer — a scan, or any image input — exports an
    EMPTY file and does NOT raise. That is a 200 with hasTextLayer false, not
    an error, and the studio's empty state depends on it staying that way.

    Output is a fixed-width spatial reconstruction: columns are preserved where
    they sit on the page, so a two-column page reads out of order line by line.
    Good for a diff or a grep, wrong for a model's context window. The rail copy
    says so; do not "fix" it here.
    """
    import time

    start = time.perf_counter()
    # The suffix carries the original extension, which the SDK's format
    # detection reads — .docx and .xlsx both work, and a bare temp name is the
    # likeliest way to turn a working format into a 500. Same idiom as
    # _prepared_pages.
    with tempfile.NamedTemporaryFile(
        suffix="-" + original_filename, delete=False
    ) as inp:
        inp.write(image_bytes)
        inp_path = inp.name

    try:
        with tempfile.TemporaryDirectory() as out_dir:
            out_path = os.path.join(out_dir, "text.txt")
            with Document.open(inp_path) as doc:
                total_pages = doc.get_page_count()
                doc.export_as_text(out_path)
            # Read inside the block: out_dir is removed when it exits.
            with open(out_path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
    finally:
        if os.path.exists(inp_path):
            os.unlink(inp_path)

    return {
        "engine": "TEXT",
        "filename": original_filename,
        "text": text,
        # Computed once, here. The frontend must not re-derive emptiness: two
        # independent literals is how a pane once read "unavailable" while Copy
        # handed over an empty string.
        "charCount": len(text),
        "wordCount": len(text.split()),
        "totalPages": total_pages,
        "hasTextLayer": bool(text.strip()),
        "code": _build_text_code(original_filename),
        "timingMs": int((time.perf_counter() - start) * 1000),
    }


def parse_field_names(raw: str) -> list[str]:
    """Accept a comma-separated list or a JSON array of field names."""
    raw = raw.strip()
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"fields looks like a JSON array but is not valid JSON: {e}") from e
        return [str(x).strip() for x in arr if str(x).strip()]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _strip_code_fence(text: str) -> str:
    """Remove a leading/trailing ```json ... ``` fence if the model added one."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_native_kv(elements: list[dict]) -> list[dict]:
    """Pull elements the SDK tagged as key-value regions. Lenient: matches on
    'key'/'value' appearing in the element type or role."""
    regions = []
    for e in elements:
        marker = (str(e.get("type", "")) + " " + str(e.get("role", ""))).lower()
        if "key" in marker or "value" in marker:
            regions.append(
                {
                    "text": e.get("text"),
                    "type": e.get("type"),
                    "role": e.get("role"),
                    "confidence": round(e.get("confidence") or 0, 2),
                    "bounds": e.get("bounds"),
                }
            )
    return regions


def _extract_schema_fields(
    image_bytes: bytes,
    original_filename: str,
    fields: list[str],
    provider: str,
) -> tuple[dict, str | None]:
    """Schema-driven extraction via a custom describe() prompt. Returns
    (parsed_fields, parse_error). On parse failure, parsed_fields is {} and
    parse_error holds the raw model text."""
    # Field names are interpolated directly into the prompt; sanitize caller
    # input before exposing this beyond trusted/demo use.
    field_list = ", ".join(fields)
    prompt = (
        "Extract the following fields from this document and return ONLY a JSON "
        f"object with these exact keys: {field_list}. Use null for any field you "
        "cannot find. Do not include any text, explanation, or code fence outside "
        "the JSON object."
    )
    result = describe_image(image_bytes, original_filename, prompt=prompt, provider=provider)
    text = _strip_code_fence(result["text"])
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, None
        return {}, text
    except (ValueError, json.JSONDecodeError):
        return {}, text


def extract_fields(
    image_bytes: bytes,
    original_filename: str,
    fields: list[str],
    provider: str = "claude",
) -> dict:
    # Two sequential VLM calls by design: native KEY_VALUE_REGION extraction
    # plus a schema-driven describe() pass. Both use the same provider.
    # Single-page by design: the schema-driven describe() pass below is
    # per-image, so the native pass stays consistent (page 1 only).
    merged, _total_pages, _processed_pages = _run_with_prerender(
        image_bytes,
        original_filename,
        "VLM",
        provider=provider,
        features=_DOCGRAPH_FEATURES,  # NAPY-20 workaround; _extract_native_kv filters to KV regions
        max_pages=1,
    )
    elements = merged.get("elements", [])
    native_regions = _extract_native_kv(elements)
    schema_fields, parse_error = _extract_schema_fields(
        image_bytes, original_filename, fields, provider
    )
    result = {
        "engine": "VLM_FIELDS",
        "filename": original_filename,
        "provider": provider,
        "requestedFields": fields,
        "schemaFields": schema_fields,
        "nativeRegions": native_regions,
        "rawElements": elements,
    }
    if parse_error is not None:
        result["parseError"] = parse_error
    return result


def _run_with_prerender(
    image_bytes: bytes,
    original_filename: str,
    engine: str,
    *,
    provider: str | None = None,
    features: int | None = None,
    output_format: VisionOutputFormat | None = None,
    max_pages: int | None = None,
    languages: str | None = None,
    table_detection: bool | None = None,
) -> tuple[dict | str, int, int]:
    """Pre-render if needed, run Vision once per page, merge.

    Returns (merged, total_pages, processed_pages) — merged is the combined
    elements dict, or page-break-joined text when output_format is MARKDOWN.

    Pages run SEQUENTIALLY (the SDK's process-wide state fragility, NAPY-7,
    makes concurrent Vision calls in one process unsafe) and FAIL FAST: after
    any Vision failure the process is poisoned, so later pages could not
    succeed anyway. The raised error is prefixed with the failing page.
    """
    with _prepared_pages(image_bytes, original_filename, max_pages=max_pages) as (
        paths,
        total_pages,
    ):
        raws: list[str] = []
        for i, path in enumerate(paths, start=1):
            try:
                raws.append(
                    _run_vision(
                        path,
                        engine,
                        provider=provider,
                        features=features,
                        output_format=output_format,
                        languages=languages,
                        table_detection=table_detection,
                    )
                )
            except (LocalVlmUnavailable, ValueError):
                raise
            except Exception as ex:
                raise RuntimeError(f"page {i}/{len(paths)}: {ex}") from ex
        if output_format is VisionOutputFormat.MARKDOWN:
            return merge_markdown_pages(raws), total_pages, len(paths)
        return merge_element_pages(raws), total_pages, len(paths)


def _extract_with_engine(
    image_bytes: bytes,
    original_filename: str,
    engine: str,
    *,
    provider: str | None = None,
    languages: str | None = None,
    table_detection: bool | None = None,
) -> dict:
    merged, total_pages, processed_pages = _run_with_prerender(
        image_bytes,
        original_filename,
        engine,
        provider=provider,
        languages=languages,
        table_detection=table_detection,
    )
    result = _format_extraction_result(merged, original_filename, engine)
    result["totalPages"] = total_pages
    result["processedPages"] = processed_pages
    return result


def _run_vision(
    path: str,
    engine: str,
    *,
    provider: str | None = None,
    features: int | None = None,
    output_format: VisionOutputFormat | None = None,
    languages: str | None = None,
    table_detection: bool | None = None,
) -> str:
    with Document.open(path) as doc:
        s = doc.get_settings()
        vs = s.get_vision_settings()
        engine_map = {
            "OCR": VisionEngine.ADAPTIVE_OCR,
            "ICR": VisionEngine.ICR,
            "VLM": VisionEngine.VLM_ENHANCED_ICR,
        }
        vs.set_engine(engine_map[engine])
        vs.set_features(features if features is not None else _LICENSED_VISION_FEATURES)
        if output_format is not None:
            vs.set_output_format(output_format)

        # Only these two OCR settings measurably change the output. favor_accuracy,
        # enable_preprocessing, enable_skew_detection and the words-detection
        # confidence threshold were all byte-identical on two documents on
        # 2026-08-06 — do not add controls for them.
        if languages is not None:
            s.get_ocr_settings().set_default_languages(languages)
        if table_detection is not None:
            s.get_ocr_settings().set_enable_table_detection(table_detection)

        if provider:
            from nutrient_sdk.vlmprovider import VlmProvider
            p = provider.lower()
            if p == "claude":
                vs.set_provider(VlmProvider.CLAUDE)
                s.get_claude_api_settings().set_api_key(os.environ["ANTHROPIC_API_KEY"])
            elif p == "openai":
                vs.set_provider(VlmProvider.OPEN_AI)
                s.get_open_ai_api_endpoint_settings().set_api_key(os.environ["OPENAI_API_KEY"])
            else:
                raise ValueError(f"Unsupported provider: {provider}")

        vision = Vision.set(doc)
        try:
            return vision.extract_content()
        except Exception as ex:
            if "localhost:1234" in str(ex) or "Connection refused" in str(ex):
                raise LocalVlmUnavailable(
                    "VLM_ENHANCED_ICR requires a local VLM server at localhost:1234 "
                    "(LM Studio / Ollama) or a VLM provider configured via "
                    "?provider=claude. Start the local server or set a provider and retry."
                ) from ex
            raise


def _format_extraction_result(merged: dict, filename: str, engine: str) -> dict:
    elements = merged.get("elements", [])
    pages = merged.get("pages", []) or []
    page_dims = {p["page"]: (p["width"], p["height"]) for p in pages}

    elements.sort(key=lambda e: e.get("readingOrder", 0))

    text_elements = []
    full_text_parts = []

    for element in elements:
        text = element.get("text")
        if not text or not text.strip():
            continue

        reading_order = element.get("readingOrder", 0)
        elem_type = element.get("type", "")
        confidence = element.get("confidence", 0)
        role = element.get("role", "")

        summary: dict = {
            "readingOrder": reading_order,
            "type": elem_type,
        }
        if role:
            summary["role"] = role
        summary["text"] = text
        summary["confidence"] = round(confidence, 2)

        words = element.get("words")
        if words:
            summary["words"] = [
                {
                    "text": w.get("text"),
                    "confidence": round(w.get("confidence", 0), 2),
                    "bounds": w.get("bounds"),
                }
                for w in words
            ]

        # 0-based page and a fractional citation, matching exactly what
        # /structured returns — that is what lets the studio's existing overlay
        # draw OCR regions with no new drawing code.
        page_1 = element.get("pageNumber")
        summary["page"] = (page_1 - 1) if isinstance(page_1, int) else None
        bounds = element.get("bounds")
        citation = None
        if bounds and page_1 in page_dims:
            w, h = page_dims[page_1]
            citation = {"page": summary["page"], **normalize_bbox(bounds, w, h)}
        summary["citation"] = citation
        summary["bounds"] = element.get("bounds")
        text_elements.append(summary)
        full_text_parts.append(f"[{reading_order}] {text}")

    confidences = [e.get("confidence", 0) for e in elements if e.get("confidence") is not None]
    avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else 0
    low_conf_count = sum(1 for c in confidences if c < 0.5)

    return {
        "engine": engine,
        "filename": filename,
        "statistics": {
            "totalElements": len(elements),
            "textElements": len(text_elements),
            "averageConfidence": avg_confidence,
            "lowConfidenceElements": low_conf_count,
        },
        "fullText": "\n".join(full_text_parts),
        "textElements": text_elements,
        "rawElements": elements,
        "pages": pages,
    }
