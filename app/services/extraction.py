import contextlib
import json
import tempfile
import os
from collections.abc import Iterator

from PIL import Image as PILImage
from nutrient_sdk import (
    Document,
    Vision,
    VisionEngine,
    VisionFeatures,
    VisionOutputFormat,
    DescriptionLevel,
)


class LocalVlmUnavailable(RuntimeError):
    """Raised when VLM_ENHANCED_ICR cannot reach its local model server."""


# `_vision_keep_alive` removed 2026-05-29 after stress-testing on
# nutrient-sdk 1.0.6 showed the native GC SIGSEGV no longer reproduces.
# Re-add if segfaults reappear.

# The license key was regenerated 2026-05-28 with the `vision_form`
# entitlement, so the full feature set is available (the previous FORM
# opt-out is gone; tests/sdk/test_vision.py guards the entitlement live).
_LICENSED_VISION_FEATURES = VisionFeatures.ALL.value

# Scanned PDFs are pre-rendered one JPEG per page; cap how many pages a single
# request may process (VLM engines make one provider API call per page).
MAX_PRERENDER_PAGES = 10

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
    next_order = 0
    for page_idx, raw in enumerate(raw_jsons, start=1):
        elements = json.loads(raw).get("elements", [])
        elements.sort(key=lambda e: e.get("readingOrder", 0))
        for el in elements:
            el["pageNumber"] = page_idx
            el["readingOrder"] = next_order
            next_order += 1
            merged.append(el)
    return {"elements": merged}


def merge_markdown_pages(texts: list[str]) -> str:
    """Join per-page Markdown with horizontal-rule page breaks."""
    return PAGE_BREAK.join(texts)


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

    export_as_image() writes a MULTI-FRAME TIFF (all pages in one call —
    verified 2026-06-04) but ignores the output extension (NAPY-16), and
    Vision cannot consume multi-frame TIFFs, so each frame is re-encoded to
    its own JPEG (q90: OpenAI rejects TIFF outright; oversized PNGs blow past
    Anthropic's 10 MB request cap after the SDK's internal upload re-encode).

    Yields (paths, total_pages): up to max_pages (default MAX_PRERENDER_PAGES)
    JPEG paths in page order, plus the document's full page count so callers
    can report truncation. Non-PDF inputs yield ([original_path], 1).
    """
    cap = MAX_PRERENDER_PAGES if max_pages is None else max_pages
    is_pdf = image_bytes[:4] == b"%PDF"
    with tempfile.NamedTemporaryFile(suffix="-" + original_filename, delete=False) as inp:
        inp.write(image_bytes)
        inp_path = inp.name

    tiff_path: str | None = None
    rendered_paths: list[str] = []
    try:
        if not is_pdf:
            yield [inp_path], 1
            return
        with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as out:
            tiff_path = out.name
        with Document.open(inp_path) as doc:
            doc.export_as_image(tiff_path)
        with PILImage.open(tiff_path) as im:
            total_pages = getattr(im, "n_frames", 1)
            for i in range(min(total_pages, cap)):
                im.seek(i)
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as page_out:
                    page_path = page_out.name
                rendered_paths.append(page_path)  # register BEFORE save so finally cleans up on failure
                im.convert("RGB").save(page_path, format="JPEG", quality=90)
        yield rendered_paths, total_pages
    finally:
        if os.path.exists(inp_path):
            os.unlink(inp_path)
        for p in ([tiff_path] if tiff_path else []) + rendered_paths:
            if os.path.exists(p):
                os.unlink(p)


@contextlib.contextmanager
def _prepared_input(image_bytes: bytes, original_filename: str) -> Iterator[str]:
    """Single-page variant of _prepared_pages — the describe path is
    inherently per-image, so it processes page 1 only (documented)."""
    with _prepared_pages(image_bytes, original_filename, max_pages=1) as (paths, _total):
        yield paths[0]


def extract_text_ocr(image_bytes: bytes, original_filename: str) -> dict:
    return _extract_with_engine(image_bytes, original_filename, "OCR")


def extract_text_icr(image_bytes: bytes, original_filename: str) -> dict:
    return _extract_with_engine(image_bytes, original_filename, "ICR")


def extract_text_vlm(image_bytes: bytes, original_filename: str, provider: str | None = None) -> dict:
    return _extract_with_engine(image_bytes, original_filename, "VLM", provider=provider)


def describe_image(
    image_bytes: bytes,
    original_filename: str,
    *,
    prompt: str | None = None,
    provider: str = "claude",
    level: str = "standard",
) -> dict:
    """Run Vision.describe() with an optional custom prompt, provider, and detail level."""
    from nutrient_sdk.vlmprovider import VlmProvider

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
    }


def _format_tables(merged: dict, filename: str, provider: str) -> dict:
    elements = merged.get("elements", [])
    tables = [e for e in elements if str(e.get("type", "")).lower() == "table"]
    return {
        "engine": "VLM_TABLES",
        "filename": filename,
        "provider": provider,
        "tableCount": len(tables),
        "tables": [
            {
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
        features=VisionFeatures.TABLE.value,
    )
    result = _format_tables(merged, original_filename, provider)
    result["totalPages"] = total_pages
    result["processedPages"] = processed_pages
    return result


def extract_markdown(image_bytes: bytes, original_filename: str, provider: str = "claude") -> dict:
    # SDK returns Markdown text directly when output_format=MARKDOWN (not JSON);
    # multi-page output is joined with PAGE_BREAK separators.
    md, total_pages, processed_pages = _run_with_prerender(
        image_bytes,
        original_filename,
        "VLM",
        provider=provider,
        output_format=VisionOutputFormat.MARKDOWN,
    )
    return {
        "engine": "VLM_MARKDOWN",
        "filename": original_filename,
        "provider": provider,
        "markdown": md,
        "charCount": len(md),
        "totalPages": total_pages,
        "processedPages": processed_pages,
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
        features=VisionFeatures.KEY_VALUE_REGION.value,
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
) -> dict:
    merged, total_pages, processed_pages = _run_with_prerender(
        image_bytes, original_filename, engine, provider=provider
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
    }
