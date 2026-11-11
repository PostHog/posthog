"""Suggested next replies to an agent answer that asks the reader for a permission, a choice, or a next step.

Every surface that shows a task conversation can offer them: Slack as buttons, the web composer as a
suggestion the person accepts with a key press.
"""

from collections.abc import Mapping
from typing import Any

from django.conf import settings

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_ai_gateway_openai_client
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.slack.channels import clip_text

logger = structlog.get_logger(__name__)

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
You write suggested replies to the PostHog agent's answer. The next message holds the answer in \
<agent_answer>. When it is known, the message that the person sent before the answer is in \
<person_message>. The person who reads the answer can send one of your replies with one click or one key press.

Use the person's message to see what they want, who decides, and which reply they will most likely send. \
Write replies only to what the answer asks or offers, not to the person's message.

First decide if the answer waits for the person. It does when it asks for permission, offers a next step, \
or asks the person to choose or to confirm. If the answer only reports a result, explains something, or asks \
nothing, return an empty list. If the next step waits for someone other than the person, such as another \
team, or for an event that has not happened yet, return an empty list. When you are not sure, return an \
empty list.

If the answer waits for the person, write up to 3 replies: the messages the person will most likely type next.

Write each reply the way a person types a short chat message to a colleague:
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
- If the answer asks the person to choose between options, write a reply for every option, up to 3. \
Do not leave out an option because the answer recommends a different one.
- If the answer asks a follow-up question that applies to only one of the options, such as "If you pick \
option 1, should I also do X?", it is part of that option, not a separate question. A reply for that option \
answers the follow-up too. If the replies are still 3 or fewer, write one reply for each answer to the \
follow-up. If not, use the answer that the agent recommends, or leave the follow-up for the agent to ask \
again. Always keep the reply for each other option.
- If the answer asks two or more separate questions that apply to all options, do not write a reply for \
each combination of answers. Write a reply only if it answers every question with a combination that the \
answer recommends. If there is none, return an empty list.
- If the answer offers to check something first and then make a change, such as a pull request or a code \
or config change, keep the two steps apart. Put first a reply that asks only for the check, so the agent \
reports what it finds and waits. A reply that also makes the change is a separate choice.
- If the answer asks for information that only the person knows, such as a name, a value or a repository, \
do not guess it. Offer only the replies that are complete without it, or return an empty list.
- If the answer asks the person to confirm a plan or a change before it starts, also offer a reply that \
asks for a change first.
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
    ai_product: str
    properties: Mapping[str, str]
    trace_id: str | None = None
    session_id: str | None = None
    distinct_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    privacy_mode: bool = False


@frozen
class SuggestedReply:
    label: str
    reply: str


_RESPONSE_FORMAT: ResponseFormatJSONSchema = {
    "type": "json_schema",
    "json_schema": {
        "name": "reply_suggestions",
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
    answer_markdown: str,
    attribution: ReplySuggestionAttribution,
    person_message: str | None = None,
    *,
    reasoning_effort: str | None = None,
) -> list[SuggestedReply]:
    """Raises on a failed call, so the offline eval can tell a failure from an answer that asks nothing."""
    if not answer_markdown.strip():
        return []
    properties = dict(attribution.properties)
    if attribution.task_id:
        properties["task_id"] = attribution.task_id
    if attribution.run_id:
        properties["run_id"] = attribution.run_id
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product=attribution.ai_product,
        trace_id=attribution.trace_id,
        session_id=attribution.session_id,
        distinct_id=attribution.distinct_id,
        properties=properties,
    ).with_options(timeout=SUGGESTIONS_TIMEOUT_SECONDS, max_retries=SUGGESTIONS_MAX_RETRIES)
    extra: dict[str, Any] = {"user": attribution.distinct_id} if attribution.distinct_id else {}
    if reasoning_effort:
        extra["reasoning_effort"] = reasoning_effort
    if attribution.privacy_mode:
        extra["extra_headers"] = {"X-PostHog-Privacy-Mode": "true"}
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
    answer_markdown: str,
    attribution: ReplySuggestionAttribution,
    person_message: str | None = None,
    *,
    reasoning_effort: str | None = None,
) -> list[SuggestedReply]:
    """Any failure returns no replies: a missing suggestion costs the reader one typed reply, and a
    wrong one sends the agent an instruction nobody gave."""
    try:
        return request_reply_suggestions(
            answer_markdown, attribution, person_message, reasoning_effort=reasoning_effort
        )
    except Exception:
        logger.warning("reply_suggestions_failed", ai_product=attribution.ai_product, exc_info=True)
        return []
