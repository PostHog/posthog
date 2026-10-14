"""One-click replies under an agent answer that waits for the reader.

After a turn ends, one fast model call reads the answer and decides whether it asks the reader
something: a permission, a choice, or an offer of a next step. If it does, the thread gets a row
of buttons with the likely replies. A click sends that reply to the agent as if the reader typed
it, so nobody has to type "yes, do it". An answer that asks nothing gets no buttons.
"""

import json
from typing import Any

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema

from posthog.llm.gateway_client import build_openai_client
from posthog.llm.semantic_enrichment import extract_json_object

logger = structlog.get_logger(__name__)

REPLY_SUGGESTION_ACTION_ID_PREFIX = "slack_app_reply_suggestion:"
REPLY_SUGGESTIONS_BLOCK_ID = "slack_app_reply_suggestions"

MAX_SUGGESTIONS = 3
# Slack rejects a button label over 75 characters, and the whole message goes down with it.
MAX_SUGGESTION_CHARS = 75

SUGGESTIONS_MODEL = "gpt-5.6-luna"
# A reasoning model spends its thinking and the JSON reply from one token budget.
SUGGESTIONS_MAX_COMPLETION_TOKENS = 2048
# The answer is already in the thread, so a slow call only delays the buttons. It must still end
# well inside the activity that delivers the answer, because that activity is sync and runs once.
SUGGESTIONS_TIMEOUT_SECONDS = 15.0
SUGGESTIONS_MAX_RETRIES = 0
# The question that asks for a reply is nearly always at the end of an answer, so a long answer
# keeps more of its tail than of its head.
ANSWER_HEAD_CHARS = 1500
ANSWER_TAIL_CHARS = 4500

# The answer goes in its own message, so text in it cannot replace these instructions.
REPLY_SUGGESTIONS_INSTRUCTIONS = """\
You write reply buttons for a Slack thread. The PostHog agent posted the answer in the next message. \
The person who reads it can send one of your replies with one click.

First decide if the answer waits for the person. It does when it:
- asks for permission, for example "Should I open a pull request?"
- offers a next step, for example "I can also add tests for the empty case."
- asks the person to choose between options or to confirm a plan.

If the answer only reports a result, explains something, or asks nothing, return an empty list. \
When you are not sure, return an empty list.

If the answer waits for the person, write up to 3 replies that the person will most likely send:
- Write each reply as the person, to the agent. For example "Yes, open the pull request", "Add the tests too", \
"Use option 2".
- Make each reply clear on its own. Write "Yes, open the pull request", not "Yes".
- Offer only actions that the answer names or clearly implies. Do not invent new work.
- Put the most likely reply first.
- Keep each reply under 60 characters.
- Write in the language of the answer.
- Do not write replies that only say thanks or close the conversation.

Answer only with JSON, for example {"suggestions": ["Yes, open the pull request", "No, keep it local"]}."""


def _response_format() -> ResponseFormatJSONSchema:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "slack_app_reply_suggestions",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"suggestions": {"type": "array", "items": {"type": "string"}}},
                "required": ["suggestions"],
                "additionalProperties": False,
            },
        },
    }


def _clip_answer(answer: str) -> str:
    if len(answer) <= ANSWER_HEAD_CHARS + ANSWER_TAIL_CHARS:
        return answer
    return f"{answer[:ANSWER_HEAD_CHARS]}\n…\n{answer[-ANSWER_TAIL_CHARS:]}"


def _clean_suggestions(raw: object) -> list[str]:
    """The usable replies, in the model's order. A label Slack would reject is dropped, not cut,
    because the label is also the text the agent receives."""
    if not isinstance(raw, list):
        return []
    suggestions: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split())
        if not text or len(text) > MAX_SUGGESTION_CHARS or text in suggestions:
            continue
        suggestions.append(text)
    return suggestions[:MAX_SUGGESTIONS]


def suggest_replies(answer_markdown: str, *, trace_id: str | None = None) -> list[str]:
    """The replies to offer under ``answer_markdown``, or an empty list when it asks nothing.

    Any failure returns an empty list: a missing button costs the reader one typed reply, and a
    wrong one sends the agent an instruction nobody gave.
    """
    if not answer_markdown.strip():
        return []
    try:
        # The same product and model as the routing classifiers, whose gateway route allows this
        # model. The classifier property lets an online evaluation scope to this call alone.
        client = build_openai_client(
            product="slack_app_routing",
            ai_product="slack_app_routing",
            trace_id=trace_id,
            properties={"slack_app_classifier": "reply_suggestions"},
        ).with_options(timeout=SUGGESTIONS_TIMEOUT_SECONDS, max_retries=SUGGESTIONS_MAX_RETRIES)
        response = client.chat.completions.create(
            model=SUGGESTIONS_MODEL,
            messages=[
                {"role": "system", "content": REPLY_SUGGESTIONS_INSTRUCTIONS},
                {"role": "user", "content": _clip_answer(answer_markdown)},
            ],
            max_completion_tokens=SUGGESTIONS_MAX_COMPLETION_TOKENS,
            response_format=_response_format(),
        )
        # Tolerant parse on top of the schema, because the gateway does not apply a response
        # format the same way on every provider route.
        parsed = extract_json_object(response.choices[0].message.content or "") or {}
        return _clean_suggestions(parsed.get("suggestions"))
    except Exception:
        logger.warning("slack_app_reply_suggestions_failed", exc_info=True)
        return []


def reply_suggestions_block(integration_id: int, suggestions: list[str]) -> dict[str, Any]:
    """One button per reply.

    Slack needs a unique action id for each element in a block, so the index is part of the id.
    The value carries the integration so the cross-region interactivity router can tell whose
    click this is, the same way the fork menu and the thumbs do.
    """
    return {
        "type": "actions",
        "block_id": REPLY_SUGGESTIONS_BLOCK_ID,
        "elements": [
            {
                "type": "button",
                "action_id": f"{REPLY_SUGGESTION_ACTION_ID_PREFIX}{index}",
                "text": {"type": "plain_text", "text": text, "emoji": True},
                "value": json.dumps({"integration_id": integration_id, "text": text}),
            }
            for index, text in enumerate(suggestions)
        ],
    }


def reply_suggestions_fallback_text(suggestions: list[str]) -> str:
    return "Suggested replies: " + ", ".join(suggestions)


def chosen_reply_blocks(slack_user_id: str, text: str) -> list[dict[str, Any]]:
    """What the suggestions message shows after a click: who replied and with what."""
    return [{"type": "context", "elements": [{"type": "mrkdwn", "text": f"<@{slack_user_id}> replied: *{text}*"}]}]


def is_reply_suggestion_action(action_id: object) -> bool:
    return isinstance(action_id, str) and action_id.startswith(REPLY_SUGGESTION_ACTION_ID_PREFIX)


def clicked_suggestion(payload: dict) -> tuple[int, str, int] | None:
    """``(integration_id, text, index)`` of the clicked reply button, or ``None``."""
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
    if not isinstance(integration_id, int) or not isinstance(text, str) or not text.strip():
        return None
    return integration_id, text.strip(), index
