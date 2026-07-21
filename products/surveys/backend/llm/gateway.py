"""LLM gateway client utilities for surveys.

Sibling of `client.py`, which calls Gemini directly with `settings.GEMINI_API_KEY`.
That key is per-deployment, so a bad value takes every direct caller down at once
with no gateway in the path to absorb it. Callers routed here borrow the gateway's
own provider credentials instead.

The gateway captures `$ai_generation` itself, so the client is deliberately NOT
wrapped with `posthoganalytics.ai` -- wrapping would double-capture every call.

Shape conformance is weaker than the Gemini path this replaces: Gemini enforced
`response_json_schema` server-side, whereas `json_object` only guarantees
syntactically valid JSON, so the schema rides in the prompt and pydantic is the
only real gate.
"""

import re
import json
import uuid
from typing import Any, TypeVar

import structlog
from openai.types.chat import ChatCompletionMessageParam
from pydantic import (
    BaseModel,
    ValidationError as PydanticValidationError,
)
from rest_framework import exceptions

from posthog.llm.gateway_client import Product, get_llm_client
from posthog.llm.semantic_enrichment import extract_json_object

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# These run inline on a DRF request thread, so they need a bound well under the
# SDK's 600s default. Retries are capped because a replayed generation is billed
# again -- nothing between here and the gateway's cost recorder deduplicates one.
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_TOKENS = 4096
MAX_RETRIES = 1

# `ai_product` and `$ai_billable` are owned by the gateway product config; sending
# them as caller headers is a documented footgun (see `get_llm_client`).
_GATEWAY_OWNED_PROPERTIES = frozenset({"ai_product", "$ai_billable"})

# Header values are ASCII on the wire and CRLF is rejected outright, so a property
# sourced from request data (a target language) would otherwise raise inside the
# SDK and surface as a 500.
_UNSAFE_HEADER_CHARS = re.compile(r"[^\x20-\x7e]")
_MAX_HEADER_VALUE_LENGTH = 200


def _header_value(value: Any) -> str:
    return _UNSAFE_HEADER_CHARS.sub("?", str(value))[:_MAX_HEADER_VALUE_LENGTH]


def _schema_instruction(response_schema: type[T]) -> str:
    return (
        "Respond with a single JSON object and nothing else. "
        f"It must conform to this JSON schema:\n{json.dumps(response_schema.model_json_schema())}"
    )


def generate_structured_output(
    *,
    product: Product,
    model: str,
    system_prompt: str,
    user_prompt: str,
    response_schema: type[T],
    posthog_properties: dict | None = None,
    team_id: int | None = None,
    distinct_id: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[T, str]:
    """Ask the gateway for JSON matching `response_schema`.

    Returns the validated model and a trace id. The trace id is generated here and
    stamped as an `llm_trace_id` event property: the gateway's OpenAI route derives
    `$ai_trace_id` itself and offers no header to override it, so the returned id
    correlates via that property rather than via `$ai_trace_id`.
    """
    client = get_llm_client(product, team_id=team_id).with_options(max_retries=MAX_RETRIES)

    trace_id = str(uuid.uuid4())
    properties = {
        key: value
        for key, value in (posthog_properties or {}).items()
        if key not in _GATEWAY_OWNED_PROPERTIES and value is not None
    }
    properties["llm_trace_id"] = trace_id

    extra_headers = {f"x-posthog-property-{key}": _header_value(value) for key, value in properties.items()}

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": f"{system_prompt}\n\n{_schema_instruction(response_schema)}"},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            timeout=timeout_seconds,
            extra_headers=extra_headers,
            user=distinct_id or product,
        )
    except Exception:
        logger.exception("llm_gateway_call_failed", model=model, product=product, properties=properties)
        raise exceptions.APIException("Failed to generate response")

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise exceptions.ValidationError("LLM gateway returned empty response")

    # `json_object` is not reliably honoured on the gateway's Anthropic route, so the
    # reply can arrive fenced or with leading prose (see `extract_json_object`).
    parsed = extract_json_object(content)
    if parsed is None:
        logger.warning("llm_gateway_unparseable_response", model=model, product=product)
        raise exceptions.APIException("Failed to generate response")

    try:
        return response_schema.model_validate(parsed), trace_id
    except PydanticValidationError:
        # Distinct from the call failure above: the model answered, the shape was wrong.
        logger.warning("llm_gateway_schema_mismatch", model=model, product=product)
        raise exceptions.APIException("Failed to generate response")
