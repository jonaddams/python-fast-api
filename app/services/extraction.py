import json
import tempfile
import os

from nutrient_sdk import Document, Vision, VisionEngine, VisionFeatures


class LocalVlmUnavailable(RuntimeError):
    """Raised when VLM_ENHANCED_ICR cannot reach its local model server."""


# `_vision_keep_alive` removed 2026-05-29 after stress-testing on
# nutrient-sdk 1.0.6 showed the native GC SIGSEGV no longer reproduces.
# Re-add if segfaults reappear.

# The demo license does not include the `vision_form` entitlement.
# `VisionFeatures.ALL` includes FORM by default, so we explicitly opt out.
_LICENSED_VISION_FEATURES = VisionFeatures.ALL.value - VisionFeatures.FORM.value


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
) -> dict:
    """Run Vision.describe() with an optional custom prompt and provider choice."""
    from nutrient_sdk.vlmprovider import VlmProvider

    with tempfile.NamedTemporaryFile(suffix="-" + original_filename, delete=False) as inp:
        inp.write(image_bytes)
        inp_path = inp.name

    try:
        with Document.open(inp_path) as doc:
            s = doc.get_settings()
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
            "promptUsed": prompt or "(default)",
            "text": text,
        }
    finally:
        os.unlink(inp_path)


def _extract_with_engine(
    image_bytes: bytes,
    original_filename: str,
    engine: str,
    *,
    provider: str | None = None,
) -> dict:
    with tempfile.NamedTemporaryFile(suffix="-" + original_filename, delete=False) as inp:
        inp.write(image_bytes)
        inp_path = inp.name

    try:
        with Document.open(inp_path) as doc:
            s = doc.get_settings()
            vs = s.get_vision_settings()
            engine_map = {
                "OCR": VisionEngine.ADAPTIVE_OCR,
                "ICR": VisionEngine.ICR,
                "VLM": VisionEngine.VLM_ENHANCED_ICR,
            }
            vision_engine = engine_map[engine]
            vs.set_engine(vision_engine)
            vs.set_features(_LICENSED_VISION_FEATURES)

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
                raw_json = vision.extract_content()
            except Exception as ex:
                if "localhost:1234" in str(ex) or "Connection refused" in str(ex):
                    raise LocalVlmUnavailable(
                        "VLM_ENHANCED_ICR requires a local VLM server at localhost:1234 "
                        "(LM Studio / Ollama) or a VLM provider configured via "
                        "?provider=claude. Start the local server or set a provider and retry."
                    ) from ex
                raise
            return _format_extraction_result(raw_json, original_filename, engine)
    finally:
        os.unlink(inp_path)


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
