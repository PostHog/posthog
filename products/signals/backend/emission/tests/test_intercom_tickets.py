import pytest

from products.signals.backend.emission.intercom_tickets import intercom_ticket_emitter


def _record(**overrides):
    return {
        "id": "100",
        "ticket_id": "7",
        "category": "Customer",
        "ticket_title": "Cannot invite teammates",
        "ticket_description": "<p>The invite button does nothing</p>",
        "ticket_state_category": "submitted",
        "ticket_type_name": "Bug report",
        "created_at": 1767225600,
        **overrides,
    }


def test_full_record_joins_title_and_description():
    output = intercom_ticket_emitter(1, _record())
    assert output is not None
    assert output.source_product == "intercom_tickets"
    assert output.source_type == "ticket"
    assert output.source_id == "100"
    assert output.description == "Cannot invite teammates\nThe invite button does nothing"
    assert output.extra == {
        "ticket_id": "7",
        "category": "Customer",
        "ticket_state_category": "submitted",
        "ticket_type_name": "Bug report",
        "created_at": "1767225600",
    }


@pytest.mark.parametrize(
    "title,description,expected",
    [
        ("Cannot invite teammates", "", "Cannot invite teammates"),
        ("", "The invite button does nothing", "The invite button does nothing"),
        (None, "<b>Bold</b> text", "Bold text"),
    ],
)
def test_description_falls_back_to_available_text(title, description, expected):
    output = intercom_ticket_emitter(1, _record(ticket_title=title, ticket_description=description))
    assert output is not None
    assert output.description == expected


def test_missing_json_keys_become_none():
    output = intercom_ticket_emitter(1, _record(ticket_state_category="", ticket_type_name="", category=None))
    assert output is not None
    assert output.extra["ticket_state_category"] is None
    assert output.extra["ticket_type_name"] is None
    assert output.extra["category"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"ticket_title": "", "ticket_description": ""},
        {"ticket_title": None, "ticket_description": "<p> </p>"},
        {"id": ""},
    ],
)
def test_record_without_id_or_text_is_skipped(overrides):
    assert intercom_ticket_emitter(1, _record(**overrides)) is None


def test_missing_id_column_raises():
    with pytest.raises(ValueError):
        intercom_ticket_emitter(1, {"ticket_title": "x"})
