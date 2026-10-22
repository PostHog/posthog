from typing import Any

import pytest

from products.signals.backend.emission.langsmith_feedback import langsmith_feedback_emitter


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": "fb-1",
        "key": "correctness",
        "score": 0,
        "value": None,
        "comment": "The answer ignores the date range",
        "correction": None,
        "run_id": "run-1",
        "trace_id": "trace-1",
        "created_at": "2026-10-01T10:00:00Z",
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, "correctness: The answer ignores the date range"),
        (
            {"correction": '{"output": "Use the last 7 days"}'},
            'correctness: The answer ignores the date range\nCorrection: {"output": "Use the last 7 days"}',
        ),
        ({"comment": None, "correction": "Use the last 7 days"}, "correctness\nCorrection: Use the last 7 days"),
        ({"comment": "   ", "correction": {"output": "fixed"}}, "correctness\nCorrection: {'output': 'fixed'}"),
        ({"key": None}, "feedback: The answer ignores the date range"),
        ({"key": ""}, "feedback: The answer ignores the date range"),
    ],
    ids=["comment_only", "comment_and_correction", "correction_only", "dict_correction", "null_key", "empty_key"],
)
def test_description_is_built_from_key_comment_and_correction(overrides: dict[str, Any], expected: str) -> None:
    output = langsmith_feedback_emitter(1, _record(**overrides))

    assert output is not None
    assert output.description == expected
    assert output.source_id == "fb-1"


@pytest.mark.parametrize(
    "overrides",
    [
        {"comment": None, "correction": None},
        {"comment": "", "correction": ""},
        {"comment": " ", "correction": "{}"},
        {"comment": None, "correction": "[]"},
        {"comment": None, "correction": "null"},
        {"id": None},
        {"id": ""},
    ],
    ids=["no_text", "empty_strings", "empty_json_object", "empty_json_list", "json_null", "null_id", "empty_id"],
)
def test_record_without_text_or_id_is_skipped(overrides: dict[str, Any]) -> None:
    assert langsmith_feedback_emitter(1, _record(**overrides)) is None


@pytest.mark.parametrize("missing", ["id", "key"])
def test_missing_required_column_raises(missing: str) -> None:
    record = _record()
    del record[missing]

    with pytest.raises(ValueError):
        langsmith_feedback_emitter(1, record)


def test_extra_coerces_scalars_to_strings() -> None:
    output = langsmith_feedback_emitter(1, _record(score=0.5, value=True))

    assert output is not None
    assert output.extra == {
        "key": "correctness",
        "score": "0.5",
        "value": "True",
        "run_id": "run-1",
        "trace_id": "trace-1",
        "created_at": "2026-10-01T10:00:00Z",
    }
