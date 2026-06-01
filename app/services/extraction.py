import contextlib
import json
import tempfile
import os
from collections.abc import Iterator

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

# The demo license does not include the `vision_form` entitlement.
# `VisionFeatures.ALL` includes FORM by default, so we explicitly opt out.
_LICENSED_VISION_FEATURES = VisionFeatures.ALL.value - VisionFeatures.FORM.value


@contextlib.contextmanager
def _prepared_input(image_bytes: bytes, original_filename: str) -> Iterator[str]:
    """Write bytes to a temp file and yield a path safe for Vision.

    PDFs are pre-rendered to a single PNG first. Image-only PDFs fail Vision's
    InputImage stage, and once one Vision call fails the SDK enters a process-wide
    bad state where every subsequent call fails identically. Pre-rendering avoids
    triggering that path. Only the first page is rasterized. See
    docs/sdk-feedback/bug-reports/.
    """
    is_pdf = image_bytes[:4] == b"%PDF"
    with tempfile.NamedTemporaryFile(suffix="-" + original_filename, delete=False) as inp:
        inp.write(image_bytes)
        inp_path = inp.name

    rendered_path: str | None = None
    try:
        if is_pdf:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as out:
                rendered_path = out.name
            with Document.open(inp_path) as doc:
                doc.export_as_image(rendered_path)
            yield rendered_path
        else:
            yield inp_path
    finally:
        os.unlink(inp_path)
        if rendered_path and os.path.exists(rendered_path):
            os.unlink(rendered_path)


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


def _format_tables(raw_json: str, filename: str, provider: str) -> dict:
    parsed = json.loads(raw_json)
    elements = parsed.get("elements", [])
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
    raw = _run_with_prerender(
        image_bytes,
        original_filename,
        "VLM",
        provider=provider,
        features=VisionFeatures.TABLE.value,
    )
    return _format_tables(raw, original_filename, provider)


def _run_with_prerender(
    image_bytes: bytes,
    original_filename: str,
    engine: str,
    *,
    provider: str | None = None,
    features: int | None = None,
    output_format: VisionOutputFormat | None = None,
) -> str:
    """Pre-render if needed, then run Vision and return the raw extract string."""
    with _prepared_input(image_bytes, original_filename) as path:
        return _run_vision(
            path,
            engine,
            provider=provider,
            features=features,
            output_format=output_format,
        )


def _extract_with_engine(
    image_bytes: bytes,
    original_filename: str,
    engine: str,
    *,
    provider: str | None = None,
) -> dict:
    raw_json = _run_with_prerender(image_bytes, original_filename, engine, provider=provider)
    return _format_extraction_result(raw_json, original_filename, engine)


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


def _format_extraction_result(raw_json: str, filename: str, engine: str) -> dict:
    parsed = json.loads(raw_json)
    elements = parsed.get("elements", [])

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
