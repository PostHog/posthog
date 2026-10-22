import json

import pytest
from unittest.mock import patch

from products.signals.backend.emission.dynatrace_problems import DYNATRACE_CONFIG, dynatrace_problem_emitter

FULL = {
    "problem_id": "P-1",
    "display_id": "P-2610",
    "title": "High CPU on web host",
    "status": "OPEN",
    "severity_level": "RESOURCE_CONTENTION",
    "impact_level": "INFRASTRUCTURE",
    "start_time": 1760000000000,
    "root_cause_entity": json.dumps({"entityId": {"id": "HOST-1", "type": "HOST"}, "name": "web-1"}),
    "affected_entities": json.dumps([{"name": "web-1"}, {"name": "web-2"}, {"name": "web-1"}]),
    "recent_comments": json.dumps(
        {
            "comments": [
                {"content": "old note", "createdAtTimestamp": 1, "authorName": "A Person"},
                {"content": "newest note", "createdAtTimestamp": 2, "authorName": "B Person"},
            ]
        }
    ),
}


def test_full_record():
    output = dynatrace_problem_emitter(1, FULL)
    assert output is not None
    assert output.source_id == "P-1"
    assert output.description == (
        "High CPU on web host\nRoot cause: web-1\nAffected: web-1, web-2\nLatest comment: newest note"
    )
    assert output.extra == {
        "display_id": "P-2610",
        "status": "OPEN",
        "severity_level": "RESOURCE_CONTENTION",
        "impact_level": "INFRASTRUCTURE",
        "start_time": "1760000000000",
        "root_cause_entity": "web-1",
        "affected_entities": ["web-1", "web-2"],
    }
    assert "Person" not in output.description


@pytest.mark.parametrize("field,value", [("problem_id", ""), ("title", ""), ("title", None)])
def test_empty_required_field_is_skipped(field, value):
    assert dynatrace_problem_emitter(1, {**FULL, field: value}) is None


def test_missing_required_column_raises():
    with pytest.raises(ValueError):
        dynatrace_problem_emitter(1, {"title": "x"})


@pytest.mark.parametrize("raw", [None, "", "not json", "[1]", "{}", '{"comments": "x"}'])
def test_bad_nested_json_still_emits_title(raw):
    output = dynatrace_problem_emitter(
        1, {**FULL, "root_cause_entity": raw, "affected_entities": raw, "recent_comments": raw}
    )
    assert output is not None
    assert output.description == "High CPU on web host"
    assert output.extra["root_cause_entity"] is None
    assert output.extra["affected_entities"] == []


def test_missing_required_column_does_not_log_comment_authors():
    record = {k: v for k, v in FULL.items() if k != "title"}
    with patch("products.signals.backend.emission.dynatrace_problems.logger") as logger:
        with pytest.raises(ValueError):
            dynatrace_problem_emitter(1, record)
    logged = logger.exception.call_args.kwargs["record"]
    assert "recent_comments" not in logged
    assert "recent_comments" in DYNATRACE_CONFIG.unloggable_fields
