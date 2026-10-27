import json

import pytest

from products.signals.backend.emission.statuspage_incidents import statuspage_incident_emitter

FULL = {
    "id": "abc",
    "page_id": "page1",
    "name": "API errors",
    "status": "investigating",
    "impact": "major",
    "shortlink": "https://stspg.io/abc",
    "incident_updates": json.dumps(
        [
            {"body": "We are looking into it", "created_at": "2026-01-01T02:00:00Z"},
            {"body": "Started investigating", "created_at": "2026-01-01T01:00:00Z"},
        ]
    ),
    "created_at": "2026-01-01T01:00:00Z",
}


def test_full_record_uses_newest_update():
    output = statuspage_incident_emitter(1, FULL)
    assert output is not None
    assert output.source_id == "page1:abc"
    assert output.description == "API errors\nWe are looking into it"
    assert output.extra == {
        "status": "investigating",
        "impact": "major",
        "shortlink": "https://stspg.io/abc",
        "created_at": "2026-01-01T01:00:00Z",
    }


def test_list_order_decides_without_timestamps():
    updates = [{"body": "newest"}, {"body": "oldest"}]
    output = statuspage_incident_emitter(1, {**FULL, "incident_updates": updates})
    assert output is not None
    assert output.description == "API errors\nnewest"


@pytest.mark.parametrize("raw", [None, "", "not json", "{}", "[]", '[{"body": ""}]', [1, "x"]])
def test_missing_or_malformed_updates_keep_name(raw):
    output = statuspage_incident_emitter(1, {**FULL, "incident_updates": raw})
    assert output is not None
    assert output.description == "API errors"


@pytest.mark.parametrize("field,value", [("id", ""), ("name", ""), ("name", None)])
def test_empty_required_field_is_skipped(field, value):
    assert statuspage_incident_emitter(1, {**FULL, field: value}) is None


def test_missing_required_column_raises():
    with pytest.raises(ValueError):
        statuspage_incident_emitter(1, {"id": "x"})


def test_same_incident_id_on_two_pages_gets_distinct_source_ids():
    first = statuspage_incident_emitter(1, FULL)
    second = statuspage_incident_emitter(1, {**FULL, "page_id": "page2"})
    assert first is not None and second is not None
    assert first.source_id != second.source_id


def test_source_id_without_page_id_is_the_incident_id():
    output = statuspage_incident_emitter(1, {k: v for k, v in FULL.items() if k != "page_id"})
    assert output is not None
    assert output.source_id == "abc"
