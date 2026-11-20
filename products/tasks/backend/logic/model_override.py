"""A model or a reasoning effort that a person asks for in the text of a message.

Every surface that takes a message for the agent can read one: Slack from a mention, the web composer
from a prompt.
"""

from collections.abc import Mapping

from django.conf import settings

import structlog
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ValidationError

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import GatewayNotConfiguredError, build_ai_gateway_openai_client
from posthog.llm.semantic_enrichment import extract_json_object

from products.tasks.backend.logic.services.model_catalogue import ModelChoice, find_model_choice, group_by_runtime

logger = structlog.get_logger(__name__)

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

# `{message_kind}` is how the prompt names the message to the classifier, such as "Slack message".
MODEL_OVERRIDE_PROMPT = """\
You are routing a {message_kind} addressed to the PostHog agent. Decide whether the author asked for THIS task to run on a particular model or reasoning effort.

Only these models can be selected — copy the id exactly as written:
{model_catalogue}

Name a model or effort only when the message instructs how to run this task:
  - "use fable for this one", "run this on opus 5", "do this with max effort", "investigate this on high".
  - The instruction can sit alongside the actual request: 'use sonnet and fix the flaky checkout test'.

Once — and only once — you have decided the message is such an instruction, resolve its shorthand to an id from the list. Nobody types a model id:
  - A bare nickname names a family, not one version: "sol", "luna", "fable".
  - A runtime or vendor in front of it is only a qualifier, and the name beside it is the answer: "codex sol" and "openai sol" both mean Sol; "claude opus" and "anthropic opus" both mean Opus.
  - Any name with no version means its newest listed member — a family word like "opus" and a nickname like "luna" alike. Take the highest-numbered entry carrying that name, never the first one you see. Read the versions as decimals: 5 is newer than 4.8, and 6 is newer than 5.6.
  - A runtime or vendor standing alone names no model: "run this on codex", "use anthropic" → null. A model id that happens to end in "codex" is a different thing, and needs its version said out loud to be chosen.

Answer with nulls when a model or effort is merely part of the subject matter — this is the common mistake, so check for it:
  - "add claude-fable-5 to our model picker" (a code change that names a model).
  - "move the summary agents over to sonnet" (a code change that switches something else onto a model, not this task).
  - "why is gpt-5 slower than opus in our evals?" (a question about models).
  - "how long does a scout take on sol 6.1, compared with terra?" (a request for data about models: the models are what gets measured, not what runs this task).
  - "the opus rollout broke the dashboard" (a topic).
  - "reasoning about this is hard" (the word, not a setting).
  - "we tried sonnet on this last week and it kept timing out" (an account of a run that already happened, not an instruction for this one — past tense is the tell).

A question or a data request about a model — its cost, speed, token use, error rate, or how it compares with other models — is subject matter. This stays true when the model name comes after "for", "via", "on", or "with". To change the run, the message must also tell you to run this task on that model.

Rules for the fields:
  - model: an id from the list above, or null if the author named no model (or named one that isn't listed).
  - reasoning_effort: only when the author explicitly asks for an effort level, and only a value listed for that model. Otherwise null.
  - An effort can be requested without a model, and a model without an effort.

When you are unsure, answer with nulls — the author's saved default is the right thing to run.

Message: {message}

Answer with the two fields, e.g. {{"model": "claude-fable-5", "reasoning_effort": "high"}} or {{"model": null, "reasoning_effort": null}}"""


@frozen
class ModelOverrideAttribution:
    ai_product: str
    properties: Mapping[str, str]
    trace_id: str | None = None


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
    message that asks for nothing."""
    prompt = MODEL_OVERRIDE_PROMPT.format(
        message_kind=message_kind, model_catalogue=_render_model_catalogue(choices), message=message
    )
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product=attribution.ai_product,
        trace_id=attribution.trace_id,
        properties=dict(attribution.properties),
    ).with_options(timeout=MODEL_OVERRIDE_TIMEOUT_SECONDS, max_retries=MODEL_OVERRIDE_MAX_RETRIES)
    response = client.chat.completions.create(
        model=MODEL_OVERRIDE_CLASSIFIER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=MODEL_OVERRIDE_MAX_COMPLETION_TOKENS,
        response_format=_response_format(choices),
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
