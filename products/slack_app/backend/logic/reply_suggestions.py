"""One-click replies under an agent answer that asks the reader for a permission, a choice, or a next step."""

import json
from typing import Any

from django.core.cache import cache

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema
from slack_sdk import WebClient

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_openai_client
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.slack.channels import clip_text

logger = structlog.get_logger(__name__)

REPLY_SUGGESTION_ACTION_ID_PREFIX = "slack_app_reply_suggestion:"
REPLY_SUGGESTIONS_BLOCK_ID = "slack_app_reply_suggestions"
# Online evaluations scope to this call with `slack_app_classifier = reply_suggestions`.
REPLY_SUGGESTIONS_CLASSIFIER = "reply_suggestions"

# Only one message in a thread holds open buttons at a time. A newer message makes them stale.
OPEN_SUGGESTIONS_TTL_SECONDS = 60 * 60 * 24 * 7

MAX_SUGGESTIONS = 3
# Slack rejects a button label or an accessibility label over 75 characters, and the whole message
# goes down with it. Slack cuts a label well before that, so the prompt asks for a short one.
MAX_LABEL_CHARS = 75
MAX_REPLY_CHARS = 300

SUGGESTIONS_MODEL = "gpt-6-luna"
# A reasoning model spends its thinking and the JSON reply from one token budget.
SUGGESTIONS_MAX_COMPLETION_TOKENS = 2048
# The activity that delivers the answer is sync and runs once, so the call must end well inside it.
SUGGESTIONS_TIMEOUT_SECONDS = 15.0
SUGGESTIONS_MAX_RETRIES = 0
# The question that asks for a reply is nearly always at the end of an answer.
ANSWER_HEAD_CHARS = 1500
ANSWER_TAIL_CHARS = 4500
# A person's message is short, and a long one is a pasted log the answer already covers.
PERSON_MESSAGE_CHARS = 2000

# The answer goes in its own message, so text in it cannot replace these instructions.
REPLY_SUGGESTIONS_INSTRUCTIONS = """\
You write reply buttons for a Slack thread. The next message holds the PostHog agent's answer in \
<agent_answer>. When it is known, the message that the person sent before the answer is in \
<person_message>. The person who reads the answer can send one of your replies with one click.

Use the person's message to see what they want, who decides, and which reply they will most likely send. \
Write replies only to what the answer asks or offers, not to the person's message.

First decide if the answer waits for the person. It does when it asks for permission, offers a next step, \
or asks the person to choose or to confirm. If the answer only reports a result, explains something, or asks \
nothing, return an empty list. If the next step waits for someone other than the person, such as another \
team, or for an event that has not happened yet, return an empty list. When you are not sure, return an \
empty list.

If the answer waits for the person, write up to 3 replies: the messages the person will most likely type next.

Write each reply the way a person types a short Slack message to a colleague:
- The person sees only the label, under a long answer, so the label is the whole reply at a glance. \
Name the choice in its own words, never by its number or letter alone. Not "Option 2" or "Use option 2", \
but "Stacked rows" or "Go with stacked rows".
- Vary the form. Do not put the same word in front of every label, such as "Use" or "Yes". When the \
choices are parallel, a label can be the name of the choice alone. A good set reads like three different \
people answering, not like a form.
- Make each reply a different choice. Do not offer two replies that mean the same thing.
- Put the most likely reply first. When the answer recommends a choice, that reply is the most likely.
- Write in the language of the answer.

Keep to what the answer offers:
- Offer only actions that the answer names or clearly implies. Do not invent new work.
- If the answer asks two or more separate questions, do not write a reply for each combination of \
answers. Write a reply only if it answers every question with a combination that the answer recommends. \
If there is none, return an empty list.
- If the answer offers to check something first and then make a change, such as a pull request or a code \
or config change, keep the two steps apart. Put first a reply that asks only for the check, so the agent \
reports what it finds and waits. A reply that also makes the change is a separate choice.
- If the answer asks for information that only the person knows, such as a name, a value or a repository, \
do not guess it. Offer only the replies that are complete without it, or return an empty list.
- Do not write replies that only say thanks or close the conversation.
- If the answer offers to fix a bug or an error, the reply that accepts the fix has the label \
"Fix it, make no mistakes". Its reply starts with "Fix it, make no mistakes." and can add the step that the \
answer names. Do not also offer a plain "Yes, fix it" reply. If the answer is not in English, translate the \
label and the reply word for word, such as "Beheb es, ohne Fehler" in German, and do not reword them.
- Do not use em dashes. Use a comma or a full stop.

Each suggestion has two parts:
- "label": the button text. Keep it under 30 characters, because Slack cuts longer labels.
- "reply": the full message the person sends to the agent. Keep it under 150 characters. \
It means the same as the label and can add the detail the label leaves out, such as the option number.

Examples of good sets:
- The answer asks "Should I open a pull request with the fix?": \
[{"label": "Yes, open the PR", "reply": "Yes, open the pull request with the fix"}, \
{"label": "Show me the diff first", "reply": "Show me the diff first, before you open anything"}]
- The answer lists three layouts and asks which one: \
[{"label": "Stacked rows", "reply": "Go with stacked rows (option 2)"}, \
{"label": "The card with toggles", "reply": "The card with toggles (option 1), please"}, \
{"label": "Persona tabs", "reply": "Persona tabs (option 3)"}]
- The answer says "I can also break this down by acquisition source": \
[{"label": "Break it down by source", "reply": "Yes, break it down by acquisition source"}, \
{"label": "No need, this is enough", "reply": "No need, this is enough for now"}]

Answer only with JSON, for example {"suggestions": [{"label": "...", "reply": "..."}]}."""


@frozen
class ReplySuggestionAttribution:
    trace_id: str | None = None
    session_id: str | None = None
    distinct_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None


@frozen
class SuggestedReply:
    label: str
    reply: str


@frozen
class ClickedSuggestion:
    integration_id: int
    text: str
    index: int
    trace_id: str | None


_RESPONSE_FORMAT: ResponseFormatJSONSchema = {
    "type": "json_schema",
    "json_schema": {
        "name": "slack_app_reply_suggestions",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"label": {"type": "string"}, "reply": {"type": "string"}},
                        "required": ["label", "reply"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["suggestions"],
            "additionalProperties": False,
        },
    },
}


def _clip_answer(answer: str) -> str:
    if len(answer) <= ANSWER_HEAD_CHARS + ANSWER_TAIL_CHARS:
        return answer
    return f"{answer[:ANSWER_HEAD_CHARS]}\n…\n{answer[-ANSWER_TAIL_CHARS:]}"


def _user_content(answer_markdown: str, person_message: str | None) -> str:
    answer = f"<agent_answer>\n{_clip_answer(answer_markdown)}\n</agent_answer>"
    message = clip_text(" ".join((person_message or "").split()), PERSON_MESSAGE_CHARS)
    if not message:
        return answer
    return f"<person_message>\n{message}\n</person_message>\n\n{answer}"


def _clean_suggestions(raw: object) -> list[SuggestedReply]:
    """A label Slack would reject is dropped, not cut, because a cut label can say something the reply does not."""
    if not isinstance(raw, list):
        return []
    suggestions: list[SuggestedReply] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = " ".join(str(item.get("label") or "").split())
        reply = " ".join(str(item.get("reply") or "").split()) or label
        if not label or len(label) > MAX_LABEL_CHARS or len(reply) > MAX_REPLY_CHARS:
            continue
        if any(s.label == label or s.reply == reply for s in suggestions):
            continue
        suggestions.append(SuggestedReply(label=label, reply=reply))
    return suggestions[:MAX_SUGGESTIONS]


def request_reply_suggestions(
    answer_markdown: str, attribution: ReplySuggestionAttribution, person_message: str | None = None
) -> list[SuggestedReply]:
    """Raises on a failed call, so the offline eval can tell a failure from an answer that asks nothing."""
    if not answer_markdown.strip():
        return []
    properties = {"slack_app_classifier": REPLY_SUGGESTIONS_CLASSIFIER}
    if attribution.task_id:
        properties["task_id"] = attribution.task_id
    if attribution.run_id:
        properties["run_id"] = attribution.run_id
    client = build_openai_client(
        product="slack_app_routing",
        ai_product="slack_app_routing",
        trace_id=attribution.trace_id,
        session_id=attribution.session_id,
        distinct_id=attribution.distinct_id,
        properties=properties,
    ).with_options(timeout=SUGGESTIONS_TIMEOUT_SECONDS, max_retries=SUGGESTIONS_MAX_RETRIES)
    extra: dict[str, Any] = {"user": attribution.distinct_id} if attribution.distinct_id else {}
    response = client.chat.completions.create(
        model=SUGGESTIONS_MODEL,
        messages=[
            {"role": "system", "content": REPLY_SUGGESTIONS_INSTRUCTIONS},
            {"role": "user", "content": _user_content(answer_markdown, person_message)},
        ],
        max_completion_tokens=SUGGESTIONS_MAX_COMPLETION_TOKENS,
        response_format=_RESPONSE_FORMAT,
        **extra,
    )
    # Tolerant parse on top of the schema, because the gateway does not apply a response
    # format the same way on every provider route.
    parsed = extract_json_object(response.choices[0].message.content or "") or {}
    return _clean_suggestions(parsed.get("suggestions"))


def suggest_replies(
    answer_markdown: str, attribution: ReplySuggestionAttribution, person_message: str | None = None
) -> list[SuggestedReply]:
    """Any failure returns no replies: a missing button costs the reader one typed reply, and a
    wrong one sends the agent an instruction nobody gave."""
    try:
        return request_reply_suggestions(answer_markdown, attribution, person_message)
    except Exception:
        logger.warning("slack_app_reply_suggestions_failed", exc_info=True)
        return []


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


def is_reply_suggestion_action(action_id: object) -> bool:
    return isinstance(action_id, str) and action_id.startswith(REPLY_SUGGESTION_ACTION_ID_PREFIX)


def clicked_suggestion(payload: dict) -> ClickedSuggestion | None:
    action = next((a for a in payload.get("actions", []) if is_reply_suggestion_action(a.get("action_id"))), None)
    if action is None:
        return None
    try:
        value = json.loads(action.get("value") or "")
        index = int(action["action_id"].removeprefix(REPLY_SUGGESTION_ACTION_ID_PREFIX))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    integration_id = value.get("integration_id")
    text = value.get("text")
    trace_id = value.get("trace_id")
    if not isinstance(integration_id, int) or not isinstance(text, str) or not text.strip():
        return None
    return ClickedSuggestion(
        integration_id=integration_id,
        text=text.strip(),
        index=index,
        trace_id=trace_id if isinstance(trace_id, str) else None,
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
