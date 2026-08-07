import pytest

from app.services.ocr_options import (
    OCR_LANGUAGES,
    UnsupportedOcrOption,
    validate_ocr_options,
)


def test_accepts_every_verified_language_code():
    # All twenty were confirmed against the SDK on 2026-08-06; the picker in the
    # studio offers exactly this set.
    for code in OCR_LANGUAGES:
        assert validate_ocr_options(code, "json")["languages"] == code


def test_accepts_plus_joined_combinations():
    assert validate_ocr_options("eng+deu+fra", "json")["languages"] == "eng+deu+fra"


@pytest.mark.parametrize("bad", ["eng,deu", "eng;deu", "eng|deu", "eng deu", "en,de"])
def test_rejects_the_separators_that_silently_return_nothing(bad):
    # THE reason this allowlist exists. Every one of these makes the SDK return
    # 154 chars / 0 elements with no exception, so a typo reads as a blank page.
    # These are regressions against observed behaviour, not invented cases.
    with pytest.raises(UnsupportedOcrOption, match="language"):
        validate_ocr_options(bad, "json")


def test_rejects_an_unknown_code_naming_the_offender():
    with pytest.raises(UnsupportedOcrOption, match="klingon"):
        validate_ocr_options("eng+klingon", "json")


def test_rejects_an_empty_language_string():
    with pytest.raises(UnsupportedOcrOption):
        validate_ocr_options("", "json")


def test_rejects_an_unknown_output_format():
    with pytest.raises(UnsupportedOcrOption, match="output format"):
        validate_ocr_options("eng", "pdf")


def test_the_listed_codes_are_exactly_the_validated_ones():
    # Listing and validation must be one source. The Bedrock work shipped a bug
    # where available_providers() and the validator disagreed about the same env
    # var (fixed in python-fast-api#33); this asserts the shape that prevents it.
    for code in OCR_LANGUAGES:
        assert validate_ocr_options(code, "json")
    assert "klingon" not in OCR_LANGUAGES
