"""A model or a reasoning effort that a person asks for in the text of a message.

Every surface that takes a message for the agent can read one: Slack from a mention, the web composer
from a prompt.
"""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django.conf import settings

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ValidationError

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import GatewayNotConfiguredError, build_ai_gateway_openai_client
from posthog.llm.prompt_templates import PromptTemplates
from posthog.llm.semantic_enrichment import extract_json_object

from products.tasks.backend.logic.services.model_catalogue import ModelChoice, find_model_choice, group_by_runtime

logger = structlog.get_logger(__name__)

prompts = PromptTemplates(Path(__file__).parent / "prompts")

# The classifier runs on a reasoning model, which draws its reasoning from the same token budget as
# the reply. The reply is one short JSON object; the headroom is for the thinking in front of it, and
# a truncated turn falls back to the safe answer. Reasoning-class is also why the cap rides on
# `max_completion_tokens`: the chat-completions route rejects `max_tokens` outright.
#
# The gateway client defaults to a 600s read and two retries, which is the right shape for a
# generation call and the wrong one here. A caller reads the message before it starts or steers a
# run, so an unbounded call holds the run back and never gets to fall back. Bounding the retries
# matters as much as the timeout, because a sync caller blocks until the client itself returns.
MODEL_OVERRIDE_CLASSIFIER_MODEL = "gpt-6-luna"
MODEL_OVERRIDE_MAX_COMPLETION_TOKENS = 2048
MODEL_OVERRIDE_TIMEOUT_SECONDS = 10.0
MODEL_OVERRIDE_MAX_RETRIES = 1


@frozen
class ModelOverrideAttribution:
    ai_product: str
    properties: Mapping[str, str]
    trace_id: str | None = None
    distinct_id: str | None = None
    privacy_mode: bool = False


@frozen
class ModelOverride:
    """What a message asks for. A message can ask for an effort without a model, and a model without an effort."""

    model: str | None
    reasoning_effort: str | None


class _ClassifierReply(BaseModel):
    model: str | None = None
    reasoning_effort: str | None = None


def _response_format(choices: tuple[ModelChoice, ...]) -> ResponseFormatJSONSchema:
    """A strict JSON schema pinning the reply to the result shape.

    The `model` enum is the point: it removes the classifier's ability to name a model
    the caller can't drive, which the prompt could only ask for and
    ``find_model_choice`` could only catch after the fact.

    `reasoning_effort` stays an unconstrained string. Which efforts are valid depends on
    the model the run finally lands on, not on the catalogue-wide union, so it is settled
    once where the preferences are resolved — constraining it here would move that
    decision to the wrong place.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "model_override",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "model": {"type": ["string", "null"], "enum": [*(c.model for c in choices), None]},
                    "reasoning_effort": {"type": ["string", "null"]},
                },
                "required": ["model", "reasoning_effort"],
                "additionalProperties": False,
            },
        },
    }


def _render_model_catalogue(choices: tuple[ModelChoice, ...]) -> str:
    """The models on offer, as the runtime → models tree `group_by_runtime` defines."""
    lines = []
    for group in group_by_runtime(choices):
        lines.append(f"{group.label} runtime:")
        for choice in group.choices:
            efforts = ", ".join(choice.supported_efforts) if choice.supported_efforts else "no effort setting"
            lines.append(f"- {choice.model} — {choice.label} (efforts: {efforts})")
    return "\n".join(lines)


def request_model_override(
    message: str,
    choices: tuple[ModelChoice, ...],
    attribution: ModelOverrideAttribution,
    *,
    message_kind: str = "message",
) -> ModelOverride | None:
    """Raises on a failed call or a reply that does not parse, so a caller can tell a failure from a
    message that asks for nothing.

    ``message_kind`` is how the prompt names the message to the classifier, such as "Slack message".
    """
    prompt = prompts.render(
        "model_override",
        message_kind=message_kind,
        model_catalogue=_render_model_catalogue(choices),
        message=message,
    )
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product=attribution.ai_product,
        trace_id=attribution.trace_id,
        distinct_id=attribution.distinct_id,
        properties=dict(attribution.properties),
    ).with_options(timeout=MODEL_OVERRIDE_TIMEOUT_SECONDS, max_retries=MODEL_OVERRIDE_MAX_RETRIES)
    extra: dict[str, Any] = {"extra_headers": {"X-PostHog-Privacy-Mode": "true"}} if attribution.privacy_mode else {}
    response = client.chat.completions.create(
        model=MODEL_OVERRIDE_CLASSIFIER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=MODEL_OVERRIDE_MAX_COMPLETION_TOKENS,
        response_format=_response_format(choices),
        **extra,
    )
    # Tolerant parse on top of the schema on purpose: the gateway fronts several
    # providers and does not honour a response format identically on every route, so
    # a reply that arrives fenced still lands rather than failing the message.
    parsed = extract_json_object(response.choices[0].message.content or "")
    # The reply has the same shape as the result, but the model is still the classifier's
    # word, not ours, until checked against the catalogue below.
    reply = _ClassifierReply.model_validate(parsed)

    choice = find_model_choice(reply.model, choices)
    if reply.model and choice is None:
        # The classifier was told to copy an id from the list; anything else is a
        # hallucination or a model we can't drive. Either way, don't act on it.
        logger.info("model_override_unknown_model", ai_product=attribution.ai_product, requested_model=reply.model)

    # The effort rides through unchecked: which efforts a model supports depends on the
    # model the run finally lands on, so it is settled once, where the preferences are
    # resolved, rather than guessed against the catalogue-wide union here.
    if choice is None and not reply.reasoning_effort:
        return None
    return ModelOverride(model=choice.model if choice else None, reasoning_effort=reply.reasoning_effort)


_WORD = re.compile(r"[a-z]+")
_EFFORT_WORDS = frozenset({"effort", "reasoning"})


def may_request_model_override(message: str, choices: tuple[ModelChoice, ...]) -> bool:
    """Whether the message names a model, a runtime, or an effort from ``choices`` at all.

    A message that names none of them cannot ask for an override, so a caller that waits for the
    classifier before it sends the message can skip the call. The check is loose on purpose: a
    false match costs one classifier call, and a missed match drops what the person asked for.
    """
    words = set(_WORD.findall(message.lower()))
    names = {
        word
        for choice in choices
        for word in _WORD.findall(f"{choice.model} {choice.label} {choice.runtime_adapter}".lower())
    }
    efforts = {effort for choice in choices for effort in choice.supported_efforts}
    return not words.isdisjoint(names | efforts | _EFFORT_WORDS)


def classify_model_override(
    message: str,
    choices: tuple[ModelChoice, ...],
    attribution: ModelOverrideAttribution,
    *,
    message_kind: str = "message",
) -> ModelOverride | None:
    """Read a per-task model or reasoning-effort request out of a message.

    Returns ``None`` when the author asked for neither — which is the overwhelming
    majority of messages, and the answer we fall back to on any parse, validation, or
    LLM failure. The cost of a miss is that the run uses the author's saved
    preferences, so every ambiguity resolves that way.

    The hard part is not spotting a model name; it is telling an instruction ("use
    fable for this") from subject matter ("add fable to the model picker"). The
    prompt is built around that distinction, and the schema restricts the answer to an
    id from ``choices``.

    Its other job is resolving the shorthand people actually type onto an id. Nobody
    writes ``gpt-5.6-sol``; they write "sol", or qualify it with the runtime or vendor
    it belongs to ("codex sol"), or name a family and leave the version off ("opus").

    Quality on both is measured by the eval suite in
    ``products/slack_app/evals/eval_model_classifier.py`` — the unit tests around this
    function cover parsing and validation, not whether the prompt reads a sentence right.
    """
    try:
        return request_model_override(message, choices, attribution, message_kind=message_kind)
    except GatewayNotConfiguredError:
        # A subclass of `ValueError`, so without this clause a missing gateway is logged as an unusable reply.
        logger.exception("model_override_classify_failed", ai_product=attribution.ai_product)
        return None
    except (ValidationError, ValueError):
        logger.info("model_override_unusable_reply", ai_product=attribution.ai_product)
        return None
    except Exception:
        logger.exception("model_override_classify_failed", ai_product=attribution.ai_product)
        return None
