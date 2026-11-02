import json

import pytest

from products.signals.backend.emission.dynatrace_problems import dynatrace_problem_emitter

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
}


def test_full_record():
    output = dynatrace_problem_emitter(1, FULL)
    assert output is not None
    assert output.source_id == "P-1"
    assert output.description == "High CPU on web host\nRoot cause: web-1\nAffected: web-1, web-2"
    assert output.extra == {
        "display_id": "P-2610",
        "status": "OPEN",
        "severity_level": "RESOURCE_CONTENTION",
        "impact_level": "INFRASTRUCTURE",
        "start_time": "1760000000000",
        "root_cause_entity": "web-1",
        "affected_entities": ["web-1", "web-2"],
    }


@pytest.mark.parametrize("field,value", [("problem_id", ""), ("title", ""), ("title", None)])
def test_empty_required_field_is_skipped(field, value):
    assert dynatrace_problem_emitter(1, {**FULL, field: value}) is None


def test_missing_required_column_raises():
    with pytest.raises(ValueError):
        dynatrace_problem_emitter(1, {"title": "x"})


@pytest.mark.parametrize("raw", [None, "", "not json", "[1]", "{}", '{"comments": "x"}'])
def test_bad_nested_json_still_emits_title(raw):
    output = dynatrace_problem_emitter(1, {**FULL, "root_cause_entity": raw, "affected_entities": raw})
    assert output is not None
    assert output.description == "High CPU on web host"
    assert output.extra["root_cause_entity"] is None
    assert output.extra["affected_entities"] == []
