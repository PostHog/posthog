import pytest

from products.signals.backend.emission.vitally_conversations import VITALLY_FIELDS, vitally_conversation_emitter


def _record(**overrides):
    return {
        "id": "abc",
        "subject": "  Login problem  ",
        "created_at": "2026-01-01T00:00:00Z",
        "external_url": "https://example.com/c/1",
        **overrides,
    }


def test_full_record_uses_subject():
    output = vitally_conversation_emitter(1, _record())
    assert output is not None
    assert output.source_id == "abc"
    assert output.description == "Login problem"
    assert output.extra == {"external_url": "https://example.com/c/1", "created_at": "2026-01-01T00:00:00Z"}


def test_messages_column_is_not_selected():
    # The Conversations list endpoint does not return messages, so the synced table has no such column.
    assert "messages" not in VITALLY_FIELDS


@pytest.mark.parametrize("subject", [None, "", "   ", 123])
def test_no_subject_returns_none(subject):
    assert vitally_conversation_emitter(1, _record(subject=subject)) is None


def test_empty_id_returns_none():
    assert vitally_conversation_emitter(1, _record(id="")) is None


def test_missing_optional_fields():
    output = vitally_conversation_emitter(1, _record(external_url=None, created_at=None))
    assert output is not None
    assert output.extra == {"external_url": None, "created_at": None}


def test_missing_id_column_raises():
    with pytest.raises(ValueError):
        vitally_conversation_emitter(1, {"subject": "x"})
