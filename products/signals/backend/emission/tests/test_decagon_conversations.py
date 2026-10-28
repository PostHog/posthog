import json

import pytest

from products.signals.backend.emission.decagon_conversations import decagon_conversation_emitter


def _record(messages, **overrides):
    return {
        "conversation_id": "conv-1",
        "created_at": "2026-01-01T00:00:00Z",
        "messages": messages,
        "csat_rating": 4,
        "tags": '["billing"]',
        **overrides,
    }


def test_full_record_uses_user_messages_only():
    messages = [
        {"role": "USER", "text": "My export fails"},
        {"role": "AI", "text": "Try again later"},
        {"role": "user", "text": "Still broken"},
    ]
    output = decagon_conversation_emitter(1, _record(json.dumps(messages)))
    assert output is not None
    assert output.source_id == "conv-1"
    assert output.description == "My export fails\nStill broken"
    assert output.extra == {"csat_rating": "4", "tags": ["billing"], "created_at": "2026-01-01T00:00:00Z"}


def test_only_first_five_user_messages_are_used():
    messages = [{"role": "USER", "text": f"m{i}"} for i in range(8)]
    output = decagon_conversation_emitter(1, _record(messages))
    assert output is not None
    assert output.description == "m0\nm1\nm2\nm3\nm4"


@pytest.mark.parametrize(
    "messages",
    [
        None,
        "",
        "not json",
        "{}",
        [],
        [{"role": "AI", "text": "hi"}],
        [{"role": "USER", "text": "   "}],
        [{"role": "USER"}],
        ["text"],
    ],
)
def test_no_user_text_returns_none(messages):
    assert decagon_conversation_emitter(1, _record(messages)) is None


def test_missing_optional_fields():
    output = decagon_conversation_emitter(
        1, _record([{"role": "USER", "text": "hi"}], csat_rating=None, tags=None, created_at=None)
    )
    assert output is not None
    assert output.extra == {"csat_rating": None, "tags": [], "created_at": None}


def test_missing_id_column_raises():
    with pytest.raises(ValueError):
        decagon_conversation_emitter(1, {"messages": []})
