import pytest

from parameterized import parameterized
from pydantic import ValidationError

from products.review_hog.backend.reviewer.models.single_agent_review import SingleAgentFinding


def _finding(priority: object) -> SingleAgentFinding:
    return SingleAgentFinding(title="t", priority=priority, file="a.py", line_start=1, body="b")


@parameterized.expand([("int", 1, "P1"), ("digit", "2", "P2"), ("tag", "P0", "P0"), ("bracket", "[P3]", "P3")])
def test_priority_accepts_common_spellings(_name: str, value: object, expected: str) -> None:
    assert _finding(value).priority == expected


@parameterized.expand([("two_digits", "10"), ("out_of_range", "P5 (was 3)"), ("empty", "")])
def test_priority_rejects_values_that_only_contain_a_digit(_name: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _finding(value)
