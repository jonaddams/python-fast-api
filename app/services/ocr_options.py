"""Adaptive OCR option validation.

ONE source for both listing and validating. The Bedrock work shipped a bug where
available_providers() read an env var raw while the validator stripped it, so the
dropdown offered a provider the request then rejected (python-fast-api#33). The
studio's language picker is built from OCR_LANGUAGES and the request is checked
against OCR_LANGUAGES, so they cannot disagree.

Why an allowlist at all: `OcrSettings.set_default_languages` accepts ONLY '+' as
a separator. Given "eng,deu" — the obvious first guess — the SDK returns 154
chars and zero elements, silently, raising nothing. A caller concludes the page
was blank. Verified 2026-08-06 across two documents; also true of ';', '|', a
space, and two-letter codes.
"""

# Verified accepted by the SDK on 2026-08-06 against
# public/documents/input_ocr_multiple_languages.png. Order is the order the
# studio offers them: the Latin-script languages a demo is most likely to want
# first, then the other scripts.
OCR_LANGUAGES: tuple[str, ...] = (
    "eng", "deu", "fra", "spa", "ita", "por", "nld", "swe", "dan", "pol",
    "tur", "ell", "rus", "jpn", "kor", "chi_sim", "chi_tra", "ara", "heb", "hin",
)

OCR_OUTPUT_FORMATS: tuple[str, ...] = ("json", "markdown")

# The separator is '+', per the SDK's own get_default_languages() default of
# 'eng' and the live probe. Do not make this configurable.
LANGUAGE_SEPARATOR = "+"


class UnsupportedOcrOption(ValueError):
    """A caller asked for an option the OCR path does not offer. Mapped to 400."""


def validate_ocr_options(languages: str, output_format: str) -> dict:
    """Return the normalised options, or raise UnsupportedOcrOption."""
    if output_format not in OCR_OUTPUT_FORMATS:
        raise UnsupportedOcrOption(
            f"unsupported output format {output_format!r}; "
            f"expected one of {', '.join(OCR_OUTPUT_FORMATS)}"
        )

    codes = [c for c in languages.split(LANGUAGE_SEPARATOR)]
    if not languages or any(not c for c in codes):
        raise UnsupportedOcrOption(
            "languages must be one or more codes joined with "
            f"{LANGUAGE_SEPARATOR!r}, e.g. 'eng' or 'eng+deu'"
        )
    for code in codes:
        if code not in OCR_LANGUAGES:
            raise UnsupportedOcrOption(
                f"unsupported language code {code!r}; expected one of "
                f"{', '.join(OCR_LANGUAGES)} joined with {LANGUAGE_SEPARATOR!r}. "
                "Note that a comma or space produces an EMPTY result from the "
                "SDK rather than an error, which is why this is rejected here."
            )
    return {"languages": languages, "outputFormat": output_format}
