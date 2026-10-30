import pytest

from products.signals.backend.emission.azure_devops_work_item_revisions import (
    azure_devops_work_item_emitter,
    html_to_text,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("", ""),
        (123, ""),
        ("plain text", "plain text"),
        ("<div>Hello <b>world</b></div>", "Hello world"),
        ("<p>One</p><p>Two &amp; three</p>", "One\nTwo & three"),
        ("line<br/>break&nbsp;here", "line\nbreak here"),
        ("<div><br></div>", ""),
    ],
)
def test_html_to_text(raw, expected):
    assert html_to_text(raw) == expected


def test_full_record():
    output = azure_devops_work_item_emitter(
        1,
        {
            "id": 77,
            "title": "Search is slow",
            "description": "<div>Takes 10s</div>",
            "state": "New",
            "work_item_type": "Bug",
            "priority": "2",
            "changed_date": "2026-01-01T00:00:00Z",
        },
    )
    assert output is not None
    assert output.source_id == "77"
    assert output.description == "Search is slow\nTakes 10s"
    assert output.extra == {
        "work_item_type": "Bug",
        "state": "New",
        "priority": "2",
        "created_at": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize("raw_priority,expected", [("", None), (None, None), ('"3"', "3"), ("1", "1")])
def test_priority_normalization(raw_priority, expected):
    output = azure_devops_work_item_emitter(1, {"id": 1, "title": "t", "priority": raw_priority})
    assert output is not None
    assert output.extra["priority"] == expected


@pytest.mark.parametrize("record", [{"id": 1, "title": ""}, {"id": 0, "title": "x"}])
def test_empty_id_or_title_is_skipped(record):
    assert azure_devops_work_item_emitter(1, record) is None


def test_missing_required_column_raises():
    with pytest.raises(ValueError):
        azure_devops_work_item_emitter(1, {"id": 1})
