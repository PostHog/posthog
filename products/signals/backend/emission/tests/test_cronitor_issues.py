import json

import pytest

from products.signals.backend.emission.cronitor_issues import cronitor_issue_emitter

FULL = {
    "key": "iss1",
    "name": "Nightly backup missed",
    "severity": "outage",
    "state": "investigating",
    "updates": json.dumps(
        [
            {"message": "Looking into it", "created": "2026-01-01T01:00:00Z"},
            {"message": "Found the cause", "created": "2026-01-01T02:00:00Z"},
        ]
    ),
    "created": "2026-01-01T00:59:00Z",
    "started": "2026-01-01T01:00:00Z",
}


def test_full_record_uses_latest_update():
    output = cronitor_issue_emitter(1, FULL)
    assert output is not None
    assert output.source_id == "iss1"
    assert output.description == "Nightly backup missed\nFound the cause"
    assert output.extra == {
        "severity": "outage",
        "state": "investigating",
        "created": "2026-01-01T00:59:00Z",
        "started": "2026-01-01T01:00:00Z",
    }


@pytest.mark.parametrize("raw", [None, "", "not json", "{}", "[]", [{"state": "identified"}]])
def test_missing_or_malformed_updates_keep_name(raw):
    output = cronitor_issue_emitter(1, {**FULL, "updates": raw})
    assert output is not None
    assert output.description == "Nightly backup missed"


@pytest.mark.parametrize("field,value", [("key", ""), ("name", ""), ("name", None)])
def test_empty_required_field_is_skipped(field, value):
    assert cronitor_issue_emitter(1, {**FULL, field: value}) is None


def test_missing_required_column_raises():
    with pytest.raises(ValueError):
        cronitor_issue_emitter(1, {"key": "x"})
