import pytest

from products.signals.backend.emission.asana_tasks import asana_task_emitter, names_from_json_list


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, []),
        ("", []),
        ("not json", []),
        ('{"name": "x"}', []),
        ('[{"gid": "1", "name": "Alpha"}, {"gid": "2"}, "bad", {"name": ""}]', ["Alpha"]),
        ([{"name": "Beta"}], ["Beta"]),
    ],
)
def test_names_from_json_list(raw, expected):
    assert names_from_json_list(raw) == expected


def test_full_record():
    output = asana_task_emitter(
        1,
        {
            "gid": "10",
            "name": "Fix login",
            "notes": "Users cannot sign in",
            "created_at": "2026-01-01T00:00:00Z",
            "permalink_url": "https://app.asana.com/0/1/10",
            "resource_subtype": "default_task",
            "projects": '[{"gid": "1", "name": "Web"}]',
            "tags": '[{"gid": "2", "name": "bug"}]',
        },
    )
    assert output is not None
    assert output.source_id == "10"
    assert output.description == "Fix login\nUsers cannot sign in"
    assert output.extra == {
        "url": "https://app.asana.com/0/1/10",
        "resource_subtype": "default_task",
        "created_at": "2026-01-01T00:00:00Z",
        "projects": ["Web"],
        "tags": ["bug"],
    }


@pytest.mark.parametrize("record", [{"gid": "1", "name": ""}, {"gid": "", "name": "x"}])
def test_empty_id_or_name_is_skipped(record):
    assert asana_task_emitter(1, record) is None


def test_missing_notes_uses_name_only():
    output = asana_task_emitter(1, {"gid": "1", "name": "Title", "notes": None})
    assert output is not None
    assert output.description == "Title"
    assert output.extra["projects"] == []


def test_missing_required_column_raises():
    with pytest.raises(ValueError):
        asana_task_emitter(1, {"name": "x"})
