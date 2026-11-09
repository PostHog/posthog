"""Slack components picked from a fixed catalog for a finished agent answer.

The catalog is one pydantic model. Its JSON schema is the response format the presenter model
follows, and the same model validates what comes back, so the prompt and the check cannot drift.
A spec that fails the check goes back to the model with the errors, once.

The model only picks and labels. A metric must quote a value the answer already states, and a link
must be a URL the answer already contains, so a presentation never shows a number or a page the
agent did not give.
"""

import json
from collections.abc import Mapping
from typing import Any

from django.conf import settings

from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_ai_gateway_openai_client
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.slack.formatting import escape_slack_mrkdwn

PRESENTATION_MODEL = "gpt-6-luna"
# Online evaluations scope to this call with `slack_app_classifier = reply_presentation`.
PRESENTATION_CLASSIFIER = "reply_presentation"
PRESENTATION_AI_PRODUCT = "slack_app_routing"
PRESENTATION_TIMEOUT_SECONDS = 8.0
PRESENTATION_MAX_COMPLETION_TOKENS = 1024
# The first try and one repair.
PRESENTATION_ATTEMPTS = 2
# Long answers keep their head, where the result usually is.
ANSWER_CHARS = 12_000

MAX_METRICS = 4
MAX_LINKS = 3
METRIC_LABEL_CHARS = 40
METRIC_VALUE_CHARS = 24
LINK_LABEL_CHARS = 30
PRESENTATION_LINKS_BLOCK_ID = "slack_app_presentation_links"


class PresentedMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        min_length=1,
        max_length=METRIC_LABEL_CHARS,
        description="What the number measures, in a few words, such as 'Weekly signups'.",
    )
    value: str = Field(
        min_length=1,
        max_length=METRIC_VALUE_CHARS,
        description="The number exactly as the answer writes it, such as '1,204' or '-12%'.",
    )


class PresentedLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        min_length=1,
        max_length=LINK_LABEL_CHARS,
        description="Button text: a short verb phrase in sentence case, such as 'Open insight'.",
    )
    url: str = Field(description="An https URL copied exactly from the answer.")


class ReplyPresentationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: list[PresentedMetric] = Field(
        max_length=MAX_METRICS,
        description="The headline numbers of the answer. Empty when the answer has no number a reader acts on.",
    )
    links: list[PresentedLink] = Field(
        max_length=MAX_LINKS,
        description="The pages a reader opens next, such as the insight, dashboard, or pull request the answer cites.",
    )

    @property
    def is_empty(self) -> bool:
        return not self.metrics and not self.links


PRESENTATION_INSTRUCTIONS = f"""You choose what a Slack reply shows next to an AI agent's answer.
The answer is already posted as text. You add a few components under it, so a reader sees the result at a glance.

Rules:
- Use only numbers and URLs that are in the answer. Copy them exactly. Never compute, round, or invent one.
- Pick at most {MAX_METRICS} metrics: the numbers that answer the question, not every number in the text.
- Pick at most {MAX_LINKS} links: the pages a reader opens next. Skip links to docs or to generic pages.
- When the answer is a plain explanation, a question back, or a code change with no numbers, return empty lists.
- Fewer components are better than weak ones.

Answer only with JSON that matches this schema:
{json.dumps(ReplyPresentationSpec.model_json_schema())}"""

_RESPONSE_FORMAT: ResponseFormatJSONSchema = {
    "type": "json_schema",
    "json_schema": {
        "name": "reply_presentation",
        # Not strict, because strict mode drops the length limits. The pydantic check enforces them instead.
        "strict": False,
        "schema": ReplyPresentationSpec.model_json_schema(),
    },
}


@frozen
class PresentationCheck:
    spec: ReplyPresentationSpec | None
    errors: tuple[str, ...] = ()


@frozen
class ReplyPresentation:
    """``spec`` is `None` when no attempt passed the check, and ``errors`` then holds the last attempt's problems."""

    spec: ReplyPresentationSpec | None
    attempts: int
    errors: tuple[str, ...] = ()


@frozen
class PresentationAttribution:
    trace_id: str | None = None
    distinct_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    privacy_mode: bool = False


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _grounding_errors(spec: ReplyPresentationSpec, answer_markdown: str) -> list[str]:
    answer = _normalized(answer_markdown)
    errors: list[str] = []
    for index, metric in enumerate(spec.metrics):
        if _normalized(metric.value) not in answer:
            errors.append(f"metrics.{index}.value: '{metric.value}' is not in the answer. Copy a value exactly.")
    for index, link in enumerate(spec.links):
        if not link.url.startswith("https://"):
            errors.append(f"links.{index}.url: use an https URL.")
        elif link.url not in answer_markdown:
            errors.append(f"links.{index}.url: '{link.url}' is not in the answer. Copy a URL exactly.")
    return errors


def check_presentation(raw: Mapping[str, Any] | None, answer_markdown: str) -> PresentationCheck:
    if raw is None:
        return PresentationCheck(spec=None, errors=("The reply is not a JSON object.",))
    try:
        spec = ReplyPresentationSpec.model_validate(raw)
    except ValidationError as error:
        return PresentationCheck(
            spec=None,
            errors=tuple(f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}" for issue in error.errors()),
        )
    grounding = _grounding_errors(spec, answer_markdown)
    if grounding:
        return PresentationCheck(spec=None, errors=tuple(grounding))
    return PresentationCheck(spec=spec)


def presentation_blocks(spec: ReplyPresentationSpec) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if spec.metrics:
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*{escape_slack_mrkdwn(metric.label)}*\n{escape_slack_mrkdwn(metric.value)}",
                    }
                    for metric in spec.metrics
                ],
            }
        )
    if spec.links:
        blocks.append(
            {
                "type": "actions",
                "block_id": PRESENTATION_LINKS_BLOCK_ID,
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": link.label, "emoji": True},
                        "url": link.url,
                    }
                    for link in spec.links
                ],
            }
        )
    return blocks


def present_reply(answer_markdown: str, attribution: PresentationAttribution) -> ReplyPresentation:
    """Raises on a failed call, so the caller can tell a failure from an answer with nothing to show."""
    properties = {"slack_app_classifier": PRESENTATION_CLASSIFIER}
    if attribution.task_id:
        properties["task_id"] = attribution.task_id
    if attribution.run_id:
        properties["run_id"] = attribution.run_id
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product=PRESENTATION_AI_PRODUCT,
        trace_id=attribution.trace_id,
        distinct_id=attribution.distinct_id,
        properties=properties,
    ).with_options(timeout=PRESENTATION_TIMEOUT_SECONDS, max_retries=0)
    extra: dict[str, Any] = {"user": attribution.distinct_id} if attribution.distinct_id else {}
    if attribution.privacy_mode:
        extra["extra_headers"] = {"X-PostHog-Privacy-Mode": "true"}

    answer = answer_markdown[:ANSWER_CHARS]
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": PRESENTATION_INSTRUCTIONS},
        {"role": "user", "content": f"<agent_answer>\n{answer}\n</agent_answer>"},
    ]
    check = PresentationCheck(spec=None)
    for attempt in range(1, PRESENTATION_ATTEMPTS + 1):
        response = client.chat.completions.create(
            model=PRESENTATION_MODEL,
            messages=messages,
            max_completion_tokens=PRESENTATION_MAX_COMPLETION_TOKENS,
            response_format=_RESPONSE_FORMAT,
            **extra,
        )
        content = response.choices[0].message.content or ""
        check = check_presentation(extract_json_object(content), answer)
        if check.spec is not None:
            return ReplyPresentation(spec=check.spec, attempts=attempt)
        messages.append({"role": "assistant", "content": content})
        messages.append(
            {
                "role": "user",
                "content": "Fix these problems and answer again:\n" + "\n".join(f"- {e}" for e in check.errors),
            }
        )
    return ReplyPresentation(spec=None, attempts=PRESENTATION_ATTEMPTS, errors=check.errors)
