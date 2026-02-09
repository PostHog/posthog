import pytest

from .fetch import _is_low_quality_survey_response_for_summarization


@pytest.mark.parametrize(
    "response,expected",
    [
        ("ddsads", True),
        ("", True),
        ("   ", True),
        ("aaaaaa", True),
        ("!!!!!!", True),
        ("asdfasdf", False),  # not super repetitive; keep (might be actual text in some languages)
        ("UI", False),
        ("ux", False),
        ("pricing", False),
        ("support", False),
        ("bug", False),
        ("slow", False),
        ("Speed", False),
        ("Needs better docs", False),
        ("too slow", False),
        ("Crash on startup", False),
        ("ok", True),  # single-token, short, not allowlisted
        ("meh", True),  # same as above
    ],
)
def test_low_quality_response_filtering(response: str, expected: bool) -> None:
    assert _is_low_quality_survey_response_for_summarization(response) is expected
