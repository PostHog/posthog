"""Classifier runner for versioned enrichment labels (the "score lab" brains).

Pure functions only: no persistence, no client construction. Callers build the OpenAI
client via `get_llm_client(product="growth")` and pass it in — this module just turns
an archived Harmonic payload plus a prompt config into a stamped verdict.
"""

import re
import json
import math
from collections.abc import Callable
from typing import Any, Literal, cast

from django.db.models import QuerySet

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential, wait_random

from posthog.llm.semantic_enrichment import extract_json_object
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

_TRUE_STRINGS = frozenset({"true", "yes", "y", "1"})
_FALSE_STRINGS = frozenset({"false", "no", "n", "0"})

# Per-call token bounds, both directions. An input_query column is whatever the query selected, so
# without these a single fat row sets the bill for the whole run.
MAX_INPUT_COLUMNS = 40
MAX_INPUT_VALUE_CHARS = 4000
MAX_INPUT_LIST_ITEMS = 50
# A verdict is a handful of short keys; anything longer is a model that has started narrating.
MAX_OUTPUT_TOKENS = 2000


class OutputParseError(ValueError):
    """The model's reply didn't satisfy the config's output schema. Deterministic: retrying the
    same prompt against the same config produces the same failure, so it is not retried."""


def verdict_field_key(config: EnrichmentPromptConfig) -> str | None:
    """Which output key represents pass/fail for unknown/summary accounting (the batch runner,
    the dry-run command): the first boolean-typed output field. None if the schema has no
    boolean field at all. Never config.name - the label is a human name, not a data key."""
    for field in config.output_fields:
        if field.get("type") == "boolean":
            return cast(str, field["key"])
    return None


def to_domain(value: Any) -> Any:
    """Reduce anything that looks like an email address to its domain, at any depth.

    Applied to every value on its way to the prompt, because the values also land in
    EnrichmentLabelResult.inputs and stay there: a provider field or a query column that happens
    to hold a personal address would otherwise be stored indefinitely. The local part carries no
    classification signal anyway - only the company domain does.

    Recurses because the values are not all scalars: tagsV2 and funding.investors are lists, and
    a HogQL column can be any JSON shape, so a top-level-only check leaves nested addresses through.
    """
    if isinstance(value, str):
        return value.rsplit("@", 1)[1].lower() if "@" in value else value
    if isinstance(value, dict):
        return {key: to_domain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_domain(item) for item in value]
    return value


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
            result[path] = to_domain(value)
    return result


def _output_instruction(config: EnrichmentPromptConfig) -> str:
    fields_desc = ", ".join(
        f'"{field["key"]}" ({field["type"]}'
        + (f", meaning: {field['description']}" if field.get("description") else "")
        + ")"
        for field in config.output_fields
    )
    return f"a JSON object with exactly these keys: {fields_desc}."


def _bounded(value: Any) -> Any:
    """Cap a single value's contribution to the prompt. A HogQL column can be an arbitrarily long
    string or list, and one row with a 200 KB description would otherwise set the bill for the
    whole run."""
    if isinstance(value, str) and len(value) > MAX_INPUT_VALUE_CHARS:
        return value[:MAX_INPUT_VALUE_CHARS] + "…"
    if isinstance(value, list) and len(value) > MAX_INPUT_LIST_ITEMS:
        return value[:MAX_INPUT_LIST_ITEMS]
    return value


def build_messages(
    config: EnrichmentPromptConfig, inputs: dict[str, Any], signup_domain: str | None
) -> list[dict[str, str]]:
    # .replace, not .format: prompt_text is free-form and may itself contain braces.
    # Domain only, never the full address: the signup email's local part is personal data
    # with no classification signal, and nothing else internal sends PII to the gateway.
    system = config.prompt_text.replace("{email}", signup_domain or "unknown")
    bounded = {key: _bounded(value) for key, value in list(inputs.items())[:MAX_INPUT_COLUMNS]}
    user = "Company data:\n" + json.dumps(bounded, indent=2) + "\n\nRespond with " + _output_instruction(config)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _coerce_bool(value: Any) -> bool:
    """Anything the model might plausibly mean by true/false, and nothing else.

    Mapping every unrecognized string to False turned "maybe" and "n/a" into a confident negative
    verdict with no error, which is the outcome the unknown path exists to avoid.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_STRINGS:
            return True
        if text in _FALSE_STRINGS:
            return False
    raise OutputParseError(f"{value!r} is not a recognizable boolean")


def _coerce_number(value: Any) -> float:
    number = float(value)
    # json.dumps writes bare NaN/Infinity, which isn't valid JSON: it breaks the run stream's
    # JSON.parse in the browser and any downstream reader of the stored output.
    if not math.isfinite(number):
        raise OutputParseError(f"{value!r} is not a finite number")
    return number


_OUTPUT_FIELD_COERCERS: dict[str, Callable[[Any], Any]] = {
    "boolean": _coerce_bool,
    "number": _coerce_number,
    "string": str,
}

# Keys whose value is a 0-1 confidence by convention, range-checked so a model answering 7.5
# doesn't get stored as if it meant something.
_UNIT_INTERVAL_KEYS = frozenset({"confidence"})


def _parse_custom_output(config: EnrichmentPromptConfig, data: dict[str, Any]) -> dict[str, Any]:
    """Validate presence and coerce basic types for a configurable output schema — the stored
    output ends up with exactly the configured keys, nothing more."""
    output: dict[str, Any] = {}
    for field in config.output_fields:
        key = field["key"]
        if key not in data:
            raise OutputParseError(f"LLM response is missing the {key!r} key")
        coercer = _OUTPUT_FIELD_COERCERS[field["type"]]
        try:
            value = coercer(data[key])
        except OutputParseError as e:
            raise OutputParseError(f"LLM response key {key!r}: {e}") from e
        except (TypeError, ValueError) as e:
            raise OutputParseError(f"LLM response key {key!r} could not be coerced to {field['type']}: {e}") from e
        if key in _UNIT_INTERVAL_KEYS and not 0 <= value <= 1:
            raise OutputParseError(f"LLM response key {key!r} is {value}, outside the 0-1 range")
        output[key] = value
    return output


@retry(
    # Only transient failures earn a retry: a reply that structurally cannot satisfy the schema
    # fails identically all three times and just triples the spend.
    retry=retry_if_not_exception_type(OutputParseError),
    stop=stop_after_attempt(3),
    # Jitter so a worker pool that all hit a 429 together doesn't retry in lockstep.
    wait=wait_exponential(multiplier=1, min=2, max=30) + wait_random(0, 2),
    reraise=True,
)
def _call_and_parse(
    config: EnrichmentPromptConfig, messages: list[dict[str, str]], client: OpenAI
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.chat.completions.create(
        model=config.model,
        messages=cast(list[ChatCompletionMessageParam], messages),
        response_format={"type": "json_object"},
        max_tokens=MAX_OUTPUT_TOKENS,
        timeout=60,
    )
    # Shared with the other products that talk to the gateway: response_format isn't reliably
    # honored on the Anthropic route, so the reply can arrive fenced or wrapped in prose.
    data = extract_json_object(response.choices[0].message.content or "")
    if data is None:
        raise OutputParseError("LLM response was not a JSON object")
    output = _parse_custom_output(config, data)
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


def _unknown_output(config: EnrichmentPromptConfig, signup_domain: str | None, reason: str) -> dict[str, Any]:
    """Only the configured keys, same as a real call: why the run was skipped goes in meta, which
    is reserved for provenance, because a schema need not have a "reasoning" key."""
    output: dict[str, Any] = {}
    verdict_key = verdict_field_key(config)
    if verdict_key is not None:
        output[verdict_key] = UNKNOWN
    output["meta"] = {"skipped": reason}
    output["inputs"] = {"signup_domain": signup_domain, "fields": {}}
    return output


def classify_payload(
    config: EnrichmentPromptConfig, payload: dict[str, Any] | None, signup_domain: str | None, client: OpenAI
) -> dict[str, Any]:
    # Not-found fetches archive core.py's _MISS_PAYLOAD ({"companyFound": False}); that's
    # evidence of absence, not a thin signal to guess from, so skip the LLM entirely.
    if not payload or payload.get("companyFound") is False:
        return _unknown_output(config, signup_domain, "missing or empty archived payload")

    # Checked after resolving, not before: a payload that's present but has none of the configured
    # paths would otherwise bill a call to ask the model about "Company data: {}".
    inputs = extract_input_fields(payload, config.input_fields)
    if not inputs:
        return _unknown_output(config, signup_domain, "archived payload has none of the configured input fields")

    messages = build_messages(config, inputs, signup_domain)
    output, meta = _call_and_parse(config, messages, client)
    output["inputs"] = {"signup_domain": signup_domain, "fields": inputs}
    if meta:
        output["meta"] = meta
    return output


def classify_row(config: EnrichmentPromptConfig, row: dict[str, Any], client: OpenAI) -> dict[str, Any]:
    """Classify one HogQL input_query result row (see enrichment/input_query.py). Every column is
    passed to the prompt, reduced to a domain if it looks like an email address (see to_domain);
    a "domain" column, if present, replaces {email} the same way signup_domain does for the
    archived-payload path (classify_payload)."""
    fields = {column: to_domain(value) for column, value in row.items()}
    domain = fields.get("domain")
    signup_domain = domain if isinstance(domain, str) else None
    messages = build_messages(config, fields, signup_domain)
    output, meta = _call_and_parse(config, messages, client)
    output["inputs"] = {"signup_domain": signup_domain, "fields": fields}
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
