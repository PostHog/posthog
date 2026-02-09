import pytest

from products.surveys.backend.summarization.fetch import (
    MIN_SINGLE_TOKEN_LENGTH_FOR_AI_SUMMARY,
    MIN_TOTAL_LENGTH_FOR_AI_SUMMARY,
    is_substantive_response_for_ai_summary,
)


@pytest.mark.parametrize(
    "response,expected",
    [
        ("", False),
        ("   ", False),
        ("!", False),
        ("!!!", False),
        ("…", False),
        ("ok", False),  # below MIN_TOTAL_LENGTH_FOR_AI_SUMMARY
        ("x" * (MIN_TOTAL_LENGTH_FOR_AI_SUMMARY - 1), False),
        ("ddsads", False),  # short single-token junk
        ("great!", False),  # short single-token - intentionally treated as low-signal for summaries
        ("bug", False),  # short single-token - intentionally treated as low-signal for summaries
        ("too slow", True),  # short but multi-token
        ("crash on launch", True),
        ("make it faster pls", True),
        ("needs dark mode", True),
        ("123", False),  # short single-token - intentionally treated as low-signal for summaries
        ("a" * MIN_SINGLE_TOKEN_LENGTH_FOR_AI_SUMMARY, True),  # boundary: allowed at threshold
        ("a" * (MIN_SINGLE_TOKEN_LENGTH_FOR_AI_SUMMARY - 1) + " a", True),  # internal whitespace makes it multi-token
    ],
)
def test_is_substantive_response_for_ai_summary(response: str, expected: bool):
    assert is_substantive_response_for_ai_summary(response) is expected
