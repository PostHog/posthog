"""Classifier runner for versioned enrichment labels (the "score lab" brains).

Pure functions only: no persistence, no client construction. Callers build the OpenAI
client via `get_llm_client(product="growth")` and pass it in — this module just turns
an archived Harmonic payload plus a prompt config into a stamped verdict.
"""

import json
from typing import Any, Literal, cast

from django.db.models import QuerySet

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from posthog.models.organization import Organization, OrganizationMembership

from products.growth.backend.models import EnrichmentPromptConfig, OrganizationEnrichmentFetch

UNKNOWN: Literal["unknown"] = "unknown"


class LabelVerdict(BaseModel):
    ai_pilled: bool
    confidence: float = Field(ge=0, le=1)
    reasoning: str = ""


def extract_input_fields(payload: dict[str, Any], input_fields: list[str]) -> dict[str, Any]:
    """Resolve dotted paths (e.g. "funding.fundingStage") into the archived payload.

    Keyed by the full dotted path so the LLM prompt shows provenance. Missing paths,
    None values, and paths that traverse through a non-dict are omitted rather than
    included as null — the prompt should only see what's actually known.
    """
    result: dict[str, Any] = {}
    for path in input_fields:
        value: Any = payload
        for part in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value is not None:
            result[path] = value
    return result


def build_messages(config: EnrichmentPromptConfig, inputs: dict[str, Any], email: str | None) -> list[dict[str, str]]:
    # .replace, not .format: prompt_text is free-form and may itself contain braces.
    system = config.prompt_text.replace("{email}", email or "unknown")
    user = (
        "Company data:\n"
        + json.dumps(inputs, indent=2)
        + '\n\nRespond with a JSON object: {"ai_pilled": boolean, "confidence": number between 0 and 1, '
        '"reasoning": string, one short sentence}.'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _strip_code_fence(raw: str) -> str:
    # Anthropic models through the gateway ignore response_format and may fence the JSON.
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
def _call_and_parse(config: EnrichmentPromptConfig, messages: list[dict[str, str]], client: OpenAI) -> LabelVerdict:
    response = client.chat.completions.create(
        model=config.model,
        messages=cast(list[ChatCompletionMessageParam], messages),
        response_format={"type": "json_object"},
        timeout=60,
    )
    raw = _strip_code_fence(response.choices[0].message.content or "")
    if not raw:
        raise ValueError("LLM returned an empty response")
    return LabelVerdict.model_validate(json.loads(raw))


def classify_payload(
    config: EnrichmentPromptConfig, payload: dict[str, Any] | None, email: str | None, client: OpenAI
) -> dict[str, Any]:
    # Not-found fetches archive core.py's _MISS_PAYLOAD ({"companyFound": False}); that's
    # evidence of absence, not a thin signal to guess from, so skip the LLM entirely.
    if not payload or payload.get("companyFound") is False:
        return {"ai_pilled": UNKNOWN, "confidence": 0.0, "reasoning": "missing or empty archived payload"}

    inputs = extract_input_fields(payload, config.input_fields)
    messages = build_messages(config, inputs, email)
    verdict = _call_and_parse(config, messages, client)
    return {"ai_pilled": verdict.ai_pilled, "confidence": verdict.confidence, "reasoning": verdict.reasoning}


def signup_email_for_organization(organization: Organization) -> str | None:
    """Earliest member's email, standing in for the signup user's identity."""
    membership = (
        OrganizationMembership.objects.filter(organization=organization)
        .select_related("user")
        .order_by("joined_at")
        .first()
    )
    return membership.user.email if membership else None


def latest_fetches_qs() -> QuerySet[OrganizationEnrichmentFetch]:
    """One row per org: its most recent archived fetch."""
    return OrganizationEnrichmentFetch.objects.order_by("organization_id", "-fetched_at", "-id").distinct(
        "organization_id"
    )


def recent_latest_fetches_qs() -> QuerySet[OrganizationEnrichmentFetch]:
    """latest_fetches_qs, but orderable and sliceable: DISTINCT ON pins the inner
    ORDER BY to organization_id, so callers wanting `-fetched_at` need this subquery wrapper."""
    return OrganizationEnrichmentFetch.objects.filter(id__in=latest_fetches_qs().values("id")).order_by("-fetched_at")


def get_active_config(label: str) -> EnrichmentPromptConfig | None:
    return EnrichmentPromptConfig.objects.filter(name=label, is_active=True).first()
