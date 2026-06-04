import json

from app.services.extraction import (
    PAGE_BREAK,
    merge_element_pages,
    merge_markdown_pages,
)


def _page(elements: list[dict]) -> str:
    return json.dumps({"elements": elements})


def test_merge_rewrites_page_numbers():
    raws = [
        _page([{"text": "a", "pageNumber": 1, "readingOrder": 0}]),
        _page([{"text": "b", "pageNumber": 1, "readingOrder": 0}]),
    ]
    merged = merge_element_pages(raws)["elements"]
    assert [e["pageNumber"] for e in merged] == [1, 2]


def test_merge_makes_reading_order_globally_sequential():
    # Page 1 elements arrive out of order; page 2 restarts at 0.
    raws = [
        _page([
            {"text": "a1", "readingOrder": 1},
            {"text": "a0", "readingOrder": 0},
        ]),
        _page([{"text": "b0", "readingOrder": 0}]),
    ]
    merged = merge_element_pages(raws)["elements"]
    # Per-page internal order preserved, then globally renumbered 0..N-1 —
    # without this, the downstream readingOrder sort interleaves pages.
    assert [e["text"] for e in merged] == ["a0", "a1", "b0"]
    assert [e["readingOrder"] for e in merged] == [0, 1, 2]


def test_merge_handles_empty_pages():
    raws = [_page([]), _page([{"text": "b", "readingOrder": 0}])]
    merged = merge_element_pages(raws)["elements"]
    assert len(merged) == 1
    assert merged[0]["pageNumber"] == 2
    assert merged[0]["readingOrder"] == 0


def test_merge_single_page_renumbers_dense_from_zero():
    # The SDK emits dense 0-based readingOrder, so renumbering is a no-op for
    # real single-page output; this pins the contract for sparse input anyway.
    raws = [_page([{"text": "a", "readingOrder": 5, "pageNumber": 1}])]
    merged = merge_element_pages(raws)["elements"]
    assert merged[0]["readingOrder"] == 0
    assert merged[0]["pageNumber"] == 1


def test_merge_markdown_joins_with_page_break():
    assert merge_markdown_pages(["one", "two"]) == f"one{PAGE_BREAK}two"


def test_merge_markdown_single_page_has_no_separator():
    assert merge_markdown_pages(["only"]) == "only"


def test_merge_empty_input_returns_empty_elements():
    assert merge_element_pages([]) == {"elements": []}
