import pytest

from products.signals.backend.emission.pylon_issues import pylon_issue_emitter


def _record(**overrides):
    return {
        "id": "issue-1",
        "number": 42,
        "title": "Export fails",
        "body_html": "<p>The CSV export&nbsp;times out</p><p>on large boards</p>",
        "state": "new",
        "type": "conversation",
        "link": "https://app.example.com/issues/42",
        "created_at": "2026-01-01T00:00:00Z",
        **overrides,
    }


def test_full_record_strips_html_from_body():
    output = pylon_issue_emitter(1, _record())
    assert output is not None
    assert output.source_product == "pylon"
    assert output.source_id == "issue-1"
    assert output.description == "Export fails\nThe CSV export times out on large boards"
    assert output.extra == {
        "number": "42",
        "state": "new",
        "type": "conversation",
        "link": "https://app.example.com/issues/42",
        "created_at": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize(
    "title,body_html,expected",
    [
        ("Export fails", None, "Export fails"),
        ("  Export fails  ", "<p></p>", "Export fails"),
        (None, "<div>Only a body</div>", "Only a body"),
        ("", "Plain &amp; simple", "Plain & simple"),
        (123, "Body with a non-string title", "Body with a non-string title"),
    ],
)
def test_description_falls_back_to_available_text(title, body_html, expected):
    output = pylon_issue_emitter(1, _record(title=title, body_html=body_html))
    assert output is not None
    assert output.description == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": None, "body_html": None},
        {"title": "  ", "body_html": "<p> </p>"},
        {"id": ""},
        {"id": None},
    ],
)
def test_record_without_id_or_text_is_skipped(overrides):
    assert pylon_issue_emitter(1, _record(**overrides)) is None


def test_missing_id_column_raises():
    with pytest.raises(ValueError):
        pylon_issue_emitter(1, {"title": "x"})
