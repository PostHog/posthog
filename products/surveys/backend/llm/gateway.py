"""LLM gateway client utilities for surveys.

Sibling of `client.py`, which calls Gemini directly with `settings.GEMINI_API_KEY`.
That key is per-deployment, so a bad value takes every direct caller down at once
with no gateway in the path to absorb it. Callers routed here borrow the gateway's
own provider credentials instead.

The gateway captures `$ai_generation` itself, so the client is deliberately NOT
wrapped with `posthoganalytics.ai` -- wrapping would double-capture every call.
"""

import json
import uuid
from typing import TypeVar

import structlog
from pydantic import BaseModel
from rest_framework import exceptions

from posthog.llm.gateway_client import Product, get_llm_client

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# `ai_product` and `$ai_billable` are owned by the gateway product config; sending
# them as caller headers is a documented footgun (see `get_llm_client`).
_GATEWAY_OWNED_PROPERTIES = frozenset({"ai_product", "$ai_billable"})


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
) -> tuple[T, str]:
    """Ask the gateway for JSON matching `response_schema`.

    Returns the validated model and a trace id. The trace id is generated here and
    stamped as an `llm_trace_id` event property: the gateway's OpenAI route derives
    `$ai_trace_id` itself and offers no header to override it, so the returned id
    correlates via that property rather than via `$ai_trace_id`.
    """
    client = get_llm_client(product, team_id=team_id)

    trace_id = str(uuid.uuid4())
    properties = {
        key: value for key, value in (posthog_properties or {}).items() if key not in _GATEWAY_OWNED_PROPERTIES
    }
    properties["llm_trace_id"] = trace_id

    extra_headers = {f"x-posthog-property-{key}": str(value) for key, value in properties.items()}

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"{system_prompt}\n\n{_schema_instruction(response_schema)}"},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            extra_headers=extra_headers,
            **({"user": distinct_id} if distinct_id else {}),
        )

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise exceptions.ValidationError("LLM gateway returned empty response")

        return response_schema.model_validate_json(content), trace_id

    except exceptions.ValidationError:
        raise
    except Exception:
        logger.exception("LLM gateway call failed", model=model, product=product, properties=properties)
        raise exceptions.APIException("Failed to generate response")
