import pytest

from products.tasks.backend.logic.stream.push_message import MAX_PUSH_MESSAGE_BYTES, PushMessage


def acp(kind: str, text: str = "") -> dict[str, object]:
    return {
        "type": "notification",
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": kind, "content": {"type": "text", "text": text}}},
        },
    }


def pi(kind: str, text: str = "", message_id: str = "message-1") -> dict[str, object]:
    return {
        "type": "pi_event",
        "event": {"type": kind, "messageId": message_id, "content": {"type": "text", "text": text}},
    }


@pytest.mark.parametrize(
    "events,expected",
    [
        ([acp("agent_message_chunk", "Done"), acp("agent_message", "Done")], "Done"),
        (
            [
                acp("agent_message", "Checking"),
                acp("tool_call"),
                acp("agent_thought_chunk", "Private"),
                acp("agent_message_chunk", "Fixed "),
                acp("agent_message_chunk", "the chart."),
            ],
            "Fixed the chart.",
        ),
        ([pi("assistant_message_chunk", "Checking"), pi("assistant_message_chunk", "Fixed", "message-2")], "Fixed"),
        ([pi("assistant_message_chunk", "Old"), pi("turn_completed"), pi("assistant_message_chunk", "New")], "New"),
        ([acp("agent_message", "Old"), acp("user_message", "Next"), acp("agent_thought_chunk", "Private")], ""),
        ([acp("agent_message_chunk", "🦔" * 400)], "🦔" * 249 + "…"),
    ],
)
def test_push_message_keeps_only_the_latest_reply(events: list[dict[str, object]], expected: str) -> None:
    message = PushMessage()
    for event in events:
        message = message.update(event) or message
        message = PushMessage.from_json(message.to_json())
    assert message.text == expected
    assert len(message.text.encode("utf-8")) <= MAX_PUSH_MESSAGE_BYTES
