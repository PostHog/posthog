"""One-click replies under an agent answer that asks the reader for a permission, a choice, or a next step."""

import json
from typing import Any

from django.core.cache import cache

import structlog
from slack_sdk import WebClient

from posthog.dataclasses import frozen

from products.tasks.backend.facade.reply_suggestions import MAX_LABEL_CHARS, ReplySuggestionAttribution, SuggestedReply

logger = structlog.get_logger(__name__)

REPLY_SUGGESTION_ACTION_ID_PREFIX = "slack_app_reply_suggestion:"
REPORT_IMPLEMENTATION_ACTION_ID = "slack_app_implement_report"
REPORT_IMPLEMENTATION_REPLY = "Fix it, make no mistakes. Implement this report and open a pull request."
REPLY_SUGGESTIONS_BLOCK_ID = "slack_app_reply_suggestions"
# Online evaluations scope to this call with `slack_app_classifier = reply_suggestions`.
REPLY_SUGGESTIONS_CLASSIFIER = "reply_suggestions"
REPLY_SUGGESTIONS_AI_PRODUCT = "slack_app_routing"

# Only one message in a thread holds open buttons at a time. A newer message makes them stale.
OPEN_SUGGESTIONS_TTL_SECONDS = 60 * 60 * 24 * 7


@frozen
class ClickedSuggestion:
    integration_id: int
    text: str
    index: int
    trace_id: str | None
    is_report_implementation: bool = False


def slack_reply_attribution(
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
    distinct_id: str | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    privacy_mode: bool = False,
) -> ReplySuggestionAttribution:
    return ReplySuggestionAttribution(
        ai_product=REPLY_SUGGESTIONS_AI_PRODUCT,
        properties={"slack_app_classifier": REPLY_SUGGESTIONS_CLASSIFIER},
        trace_id=trace_id,
        session_id=session_id,
        distinct_id=distinct_id,
        task_id=task_id,
        run_id=run_id,
        privacy_mode=privacy_mode,
    )


def reply_suggestions_block(
    integration_id: int, suggestions: list[SuggestedReply], trace_id: str | None
) -> dict[str, Any]:
    """The index is part of the action id, because Slack needs a unique one for each element in a block.

    Slack has no tooltip on a button, so the full reply reaches only screen readers, through the
    accessibility label. The value carries it too, because a click sends it. The integration in the
    value lets the cross-region interactivity router claim the click.
    """
    return {
        "type": "actions",
        "block_id": REPLY_SUGGESTIONS_BLOCK_ID,
        "elements": [
            {
                "type": "button",
                "action_id": f"{REPLY_SUGGESTION_ACTION_ID_PREFIX}{index}",
                "text": {"type": "plain_text", "text": suggestion.label, "emoji": True},
                "accessibility_label": suggestion.reply[:MAX_LABEL_CHARS],
                "value": json.dumps({"integration_id": integration_id, "trace_id": trace_id, "text": suggestion.reply}),
            }
            for index, suggestion in enumerate(suggestions)
        ],
    }


def reply_suggestions_fallback_text(suggestions: list[SuggestedReply]) -> str:
    return "Suggested replies: " + ", ".join(suggestion.label for suggestion in suggestions)


def report_implementation_button(integration_id: int) -> dict[str, Any]:
    return {
        "type": "button",
        "action_id": REPORT_IMPLEMENTATION_ACTION_ID,
        "text": {"type": "plain_text", "text": "Implement", "emoji": True},
        "style": "primary",
        "value": json.dumps({"integration_id": integration_id}),
    }


def is_reply_suggestion_action(action_id: object) -> bool:
    return isinstance(action_id, str) and (
        action_id == REPORT_IMPLEMENTATION_ACTION_ID or action_id.startswith(REPLY_SUGGESTION_ACTION_ID_PREFIX)
    )


def clicked_suggestion(payload: dict) -> ClickedSuggestion | None:
    action = next((a for a in payload.get("actions", []) if is_reply_suggestion_action(a.get("action_id"))), None)
    if action is None:
        return None
    is_report_implementation = action["action_id"] == REPORT_IMPLEMENTATION_ACTION_ID
    try:
        value = json.loads(action.get("value") or "")
        index = (
            0 if is_report_implementation else int(action["action_id"].removeprefix(REPLY_SUGGESTION_ACTION_ID_PREFIX))
        )
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    integration_id = value.get("integration_id")
    text = REPORT_IMPLEMENTATION_REPLY if is_report_implementation else value.get("text")
    trace_id = value.get("trace_id")
    if not isinstance(integration_id, int) or not isinstance(text, str) or not text.strip():
        return None
    return ClickedSuggestion(
        integration_id=integration_id,
        text=text.strip(),
        index=index,
        trace_id=trace_id if isinstance(trace_id, str) else None,
        is_report_implementation=is_report_implementation,
    )


def _open_suggestions_key(integration_id: int, channel: str, thread_ts: str) -> str:
    return f"slack_app_reply_suggestions_open:{integration_id}:{channel}:{thread_ts}"


def remember_open_suggestions(integration_id: int, channel: str, thread_ts: str, message_ts: str) -> None:
    cache.set(_open_suggestions_key(integration_id, channel, thread_ts), message_ts, OPEN_SUGGESTIONS_TTL_SECONDS)


def clear_open_suggestions(client: WebClient, integration_id: int, channel: str, thread_ts: str) -> None:
    """Remove buttons that a newer message in the thread made stale, so nobody answers an old question.

    The message is read back from Slack because a streamed answer's blocks exist only there. Slack
    can only replace a message whole, so it is sent back without the buttons, or deleted when the
    buttons were all it held.
    """
    key = _open_suggestions_key(integration_id, channel, thread_ts)
    message_ts = cache.get(key)
    if not isinstance(message_ts, str):
        return
    cache.delete(key)
    try:
        response = client.conversations_replies(
            channel=channel, ts=message_ts, oldest=message_ts, latest=message_ts, inclusive=True, limit=1
        )
        message = next((m for m in response.get("messages") or [] if m.get("ts") == message_ts), None)
        if message is None:
            return
        blocks = message.get("blocks") or []
        kept = [block for block in blocks if block.get("block_id") != REPLY_SUGGESTIONS_BLOCK_ID]
        if len(kept) == len(blocks):
            return
        if kept:
            client.chat_update(channel=channel, ts=message_ts, text=message.get("text") or "", blocks=kept)
        else:
            client.chat_delete(channel=channel, ts=message_ts)
    except Exception:
        logger.warning(
            "slack_app_reply_suggestions_clear_failed", channel=channel, message_ts=message_ts, exc_info=True
        )
