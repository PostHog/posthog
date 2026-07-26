"""Classifier runner for versioned enrichment labels (the "score lab" brains).

Pure functions only: no persistence, no client construction. Callers build the OpenAI
client via `get_llm_client(product="growth")` and pass it in — this module just turns
an archived Harmonic payload plus a prompt config into a stamped verdict.
"""

import re
import json
from collections.abc import Callable
from typing import Any, Literal, cast

from django.db.models import QuerySet

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from posthog.models.organization import Organization, OrganizationMembership

from products.growth.backend.models import EnrichmentPromptConfig, OrganizationEnrichmentFetch

UNKNOWN: Literal["unknown"] = "unknown"

# Output schema constraints for EnrichmentPromptConfig.output_fields (see its docstring). Shared
# by the API's save/run validation (products/growth/backend/api/score_lab.py) and the coercion
# below - single source of truth so the two can never drift.
OUTPUT_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
OUTPUT_FIELD_TYPES = ("boolean", "number", "string")
# Keys the stored output dict uses for provenance (see classify_payload/classify_row below) -
# a configured output field can never shadow them.
RESERVED_OUTPUT_FIELD_KEYS = frozenset({"meta", "inputs"})


class LabelVerdict(BaseModel):
    verdict: bool
    confidence: float = Field(ge=0, le=1)
    reasoning: str = ""


def verdict_field_key(config: EnrichmentPromptConfig) -> str | None:
    """Which output key represents pass/fail for unknown/summary accounting (the batch runner,
    the dry-run command): the label name for a legacy config, or the first boolean-typed field
    for a configurable output schema. None if a custom schema has no boolean field at all."""
    if not config.output_fields:
        return config.name
    for field in config.output_fields:
        if field.get("type") == "boolean":
            return cast(str, field["key"])
    return None


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


def _output_instruction(config: EnrichmentPromptConfig) -> str:
    if not config.output_fields:
        # The verdict key is the label name — the runner serves every label, not just ai_pilled.
        return (
            'a JSON object: {"' + config.name + '": boolean, "confidence": number between 0 and 1, '
            '"reasoning": string, one short sentence}.'
        )
    fields_desc = ", ".join(
        f'"{field["key"]}" ({field["type"]}'
        + (f", meaning: {field['description']}" if field.get("description") else "")
        + ")"
        for field in config.output_fields
    )
    return f"a JSON object with exactly these keys: {fields_desc}."


def build_messages(
    config: EnrichmentPromptConfig, inputs: dict[str, Any], signup_domain: str | None
) -> list[dict[str, str]]:
    # .replace, not .format: prompt_text is free-form and may itself contain braces.
    # Domain only, never the full address: the signup email's local part is personal data
    # with no classification signal, and nothing else internal sends PII to the gateway.
    system = config.prompt_text.replace("{email}", signup_domain or "unknown")
    user = "Company data:\n" + json.dumps(inputs, indent=2) + "\n\nRespond with " + _output_instruction(config)
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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


_OUTPUT_FIELD_COERCERS: dict[str, Callable[[Any], Any]] = {
    "boolean": _coerce_bool,
    "number": float,
    "string": str,
}


def _parse_custom_output(config: EnrichmentPromptConfig, data: dict[str, Any]) -> dict[str, Any]:
    """Validate presence and coerce basic types for a configurable output schema — the stored
    output ends up with exactly the configured keys, nothing more."""
    output: dict[str, Any] = {}
    for field in config.output_fields:
        key = field["key"]
        if key not in data:
            raise ValueError(f"LLM response is missing the {key!r} key")
        coercer = _OUTPUT_FIELD_COERCERS[field["type"]]
        try:
            output[key] = coercer(data[key])
        except (TypeError, ValueError) as e:
            raise ValueError(f"LLM response key {key!r} could not be coerced to {field['type']}: {e}") from e
    return output


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
def _call_and_parse(
    config: EnrichmentPromptConfig, messages: list[dict[str, str]], client: OpenAI
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.chat.completions.create(
        model=config.model,
        messages=cast(list[ChatCompletionMessageParam], messages),
        response_format={"type": "json_object"},
        timeout=60,
    )
    raw = _strip_code_fence(response.choices[0].message.content or "")
    if not raw:
        raise ValueError("LLM returned an empty response")
    data = json.loads(raw)
    if config.output_fields:
        output = _parse_custom_output(config, data)
    else:
        if config.name not in data:
            raise ValueError(f"LLM response is missing the {config.name!r} verdict key")
        verdict = LabelVerdict(
            verdict=data[config.name], confidence=data.get("confidence", 0.0), reasoning=data.get("reasoning", "")
        )
        output = {config.name: verdict.verdict, "confidence": verdict.confidence, "reasoning": verdict.reasoning}
    return output, _response_meta(response)


def _response_meta(response: Any) -> dict[str, Any]:
    """What the gateway actually served, stamped per result: config.model is an alias the
    provider can silently repoint, and usage tokens are the raw input to spend-per-config."""
    meta: dict[str, Any] = {}
    served_model = getattr(response, "model", None)
    if isinstance(served_model, str):
        meta["response_model"] = served_model
    fingerprint = getattr(response, "system_fingerprint", None)
    if isinstance(fingerprint, str):
        meta["system_fingerprint"] = fingerprint
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        meta["prompt_tokens"] = prompt_tokens
        meta["completion_tokens"] = completion_tokens
    return meta


def classify_payload(
    config: EnrichmentPromptConfig, payload: dict[str, Any] | None, signup_domain: str | None, client: OpenAI
) -> dict[str, Any]:
    # Not-found fetches archive core.py's _MISS_PAYLOAD ({"companyFound": False}); that's
    # evidence of absence, not a thin signal to guess from, so skip the LLM entirely.
    if not payload or payload.get("companyFound") is False:
        output: dict[str, Any] = {"confidence": 0.0, "reasoning": "missing or empty archived payload"}
        verdict_key = verdict_field_key(config)
        if verdict_key is not None:
            output[verdict_key] = UNKNOWN
        output["inputs"] = {"signup_domain": signup_domain, "fields": {}}
        return output

    inputs = extract_input_fields(payload, config.input_fields)
    messages = build_messages(config, inputs, signup_domain)
    output, meta = _call_and_parse(config, messages, client)
    output["inputs"] = {"signup_domain": signup_domain, "fields": inputs}
    if meta:
        output["meta"] = meta
    return output


def classify_row(config: EnrichmentPromptConfig, row: dict[str, Any], client: OpenAI) -> dict[str, Any]:
    """Classify one HogQL input_query result row (see enrichment/input_query.py). Every column
    is passed to the prompt as-is; a "domain" column, if present, replaces {email} the same way
    signup_domain does for the archived-payload path (classify_payload)."""
    domain = row.get("domain")
    signup_domain = domain if isinstance(domain, str) else None
    messages = build_messages(config, row, signup_domain)
    output, meta = _call_and_parse(config, messages, client)
    output["inputs"] = {"signup_domain": signup_domain, "fields": row}
    if meta:
        output["meta"] = meta
    return output


def signup_domain_for_organization(organization: Organization) -> str | None:
    """Earliest member's email domain, standing in for the signup company identity."""
    membership = (
        OrganizationMembership.objects.filter(organization=organization)
        .select_related("user")
        .order_by("joined_at")
        .first()
    )
    if membership is None or not membership.user.email or "@" not in membership.user.email:
        return None
    return membership.user.email.rsplit("@", 1)[1].lower()


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
