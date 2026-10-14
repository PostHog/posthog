import pytest

from parameterized import parameterized
from pydantic import ValidationError

from products.review_hog.backend.reviewer.models.single_agent_review import SingleAgentFinding, SingleAgentReview


def _finding(priority: object) -> SingleAgentFinding:
    return SingleAgentFinding(title="t", priority=priority, file="a.py", line_start=1, body="b")


@parameterized.expand([("int", 1, "P1"), ("digit", "2", "P2"), ("tag", "P0", "P0"), ("bracket", "[P3]", "P3")])
def test_priority_accepts_common_spellings(_name: str, value: object, expected: str) -> None:
    assert _finding(value).priority == expected


@parameterized.expand([("two_digits", "10"), ("out_of_range", "P5 (was 3)"), ("empty", "")])
def test_priority_rejects_values_that_only_contain_a_digit(_name: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _finding(value)


@parameterized.expand(
    [
        ("findings_missing", {"overall_correctness": "patch is correct"}, None),
        ("findings_empty", {"findings": []}, 0),
    ]
)
def test_a_reply_without_findings_fails_instead_of_reading_as_clean(
    _name: str, reply: dict[str, object], expected_count: int | None
) -> None:
    # A malformed reply that reads as "no findings" posts a clean review for a PR nobody reviewed.
    if expected_count is None:
        with pytest.raises(ValidationError):
            SingleAgentReview.model_validate(reply)
    else:
        assert len(SingleAgentReview.model_validate(reply).findings) == expected_count
