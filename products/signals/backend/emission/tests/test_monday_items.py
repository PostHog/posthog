import json

import pytest

from products.signals.backend.emission.monday_items import monday_body, monday_item_emitter


def _columns(*cols):
    return json.dumps([{"id": f"c{i}", "type": t, "text": text} for i, (t, text) in enumerate(cols)])


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("not json", ""),
        ("{}", ""),
        (_columns(("long_text", "Details here")), "Details here"),
        (_columns(("text", "One"), ("long_text", "Two")), "One\nTwo"),
        (_columns(("people", "Jane Doe"), ("email", "a@example.com"), ("phone", "123")), ""),
        (_columns(("text", "  "), ("long_text", None)), ""),
        (json.dumps(["bad", {"type": "text", "text": "ok"}]), "ok"),
    ],
)
def test_monday_body(raw, expected):
    assert monday_body(raw) == expected


def test_full_record():
    output = monday_item_emitter(
        1,
        {
            "id": "55",
            "name": "Crash on export",
            "state": "active",
            "group_title": "Bugs",
            "column_values": _columns(("long_text", "Happens on large boards")),
            "created_at": "2026-01-01T00:00:00Z",
            "board_id": 9,
        },
    )
    assert output is not None
    assert output.source_id == "55"
    assert output.description == "Crash on export\nHappens on large boards"
    assert output.extra == {
        "state": "active",
        "group": "Bugs",
        "board_id": "9",
        "created_at": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize("record", [{"id": "1", "name": ""}, {"id": "", "name": "x"}])
def test_empty_id_or_name_is_skipped(record):
    assert monday_item_emitter(1, record) is None


def test_missing_required_column_raises():
    with pytest.raises(ValueError):
        monday_item_emitter(1, {"id": "1"})
