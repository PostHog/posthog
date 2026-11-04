import json

import pytest

from products.signals.backend.emission.instatus_incidents import instatus_incident_emitter

FULL = {
    "id": "inc1",
    "page_id": "page1",
    "name": "Checkout is slow",
    "status": "IDENTIFIED",
    "started": "2026-01-01T01:00:00Z",
    "updates": json.dumps(
        [
            {"message": "Investigating", "started": "2026-01-01T01:00:00Z"},
            {"message": "Cause identified", "started": "2026-01-01T02:00:00Z"},
        ]
    ),
    "components": json.dumps([{"id": "c1", "name": "Checkout"}, {"id": "c2", "name": "Payments"}, "Checkout"]),
}


def test_full_record():
    output = instatus_incident_emitter(1, FULL)
    assert output is not None
    assert output.source_id == "page1:inc1"
    assert output.description == "Checkout is slow\nCause identified\nAffected components: Checkout, Payments"
    assert output.extra == {
        "status": "IDENTIFIED",
        "started": "2026-01-01T01:00:00Z",
        "components": ["Checkout", "Payments"],
    }


@pytest.mark.parametrize("raw", [None, "", "not json", "{}", "[]", "[1, null]"])
def test_malformed_nested_json_keeps_name(raw):
    output = instatus_incident_emitter(1, {**FULL, "updates": raw, "components": raw})
    assert output is not None
    assert output.description == "Checkout is slow"
    assert output.extra["components"] == []


@pytest.mark.parametrize("field,value", [("id", ""), ("name", ""), ("name", None)])
def test_empty_required_field_is_skipped(field, value):
    assert instatus_incident_emitter(1, {**FULL, field: value}) is None


def test_missing_required_column_raises():
    with pytest.raises(ValueError):
        instatus_incident_emitter(1, {"id": "x"})


def test_same_incident_id_on_two_pages_gets_distinct_source_ids():
    first = instatus_incident_emitter(1, FULL)
    second = instatus_incident_emitter(1, {**FULL, "page_id": "page2"})
    assert first is not None and second is not None
    assert first.source_id != second.source_id


def test_source_id_without_page_id_is_the_incident_id():
    output = instatus_incident_emitter(1, {k: v for k, v in FULL.items() if k != "page_id"})
    assert output is not None
    assert output.source_id == "inc1"
