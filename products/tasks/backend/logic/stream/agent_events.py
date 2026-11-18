from typing import Any

AGENT_COMMAND_DISPATCHED_METHOD = "_posthog/agent_command_dispatched"

_ACP_GENERATION_UPDATES = frozenset(
    {
        "agent_message",
        "agent_message_chunk",
        "agent_thought_chunk",
        "tool_call",
        "tool_call_update",
    }
)

_PI_GENERATION_EVENTS = frozenset(
    {
        "assistant_message_chunk",
        "assistant_thought_chunk",
        "tool_call_started",
        "tool_call_updated",
    }
)


def is_agent_command_dispatched(event: dict[str, Any]) -> bool:
    notification = event.get("notification")
    return (
        event.get("type") == "notification"
        and isinstance(notification, dict)
        and notification.get("method") == AGENT_COMMAND_DISPATCHED_METHOD
    )


def is_agent_generation_event(event: dict[str, Any]) -> bool:
    if event.get("type") == "pi_event":
        pi_event = event.get("event")
        return isinstance(pi_event, dict) and pi_event.get("type") in _PI_GENERATION_EVENTS

    notification = event.get("notification")
    if event.get("type") != "notification" or not isinstance(notification, dict):
        return False
    if notification.get("method") != "session/update":
        return False
    params = notification.get("params")
    if not isinstance(params, dict):
        return False
    update = params.get("update")
    return isinstance(update, dict) and update.get("sessionUpdate") in _ACP_GENERATION_UPDATES
