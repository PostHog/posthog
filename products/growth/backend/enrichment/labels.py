"""Classifier runner for versioned AI enrichment labels.

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

from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, wait_random

from posthog.llm.semantic_enrichment import extract_json_object
from posthog.models.organization import Organization, OrganizationMembership

from products.growth.backend.models import EnrichmentPromptConfig, OrganizationEnrichmentFetch

UNKNOWN: Literal["unknown"] = "unknown"

# Keys the stored output dict uses for provenance (see classify_payload below).
# validate_output_fields rejects any configured output field that shadows one of these.
RESERVED_OUTPUT_FIELD_KEYS = frozenset({"meta", "inputs"})

# Schema constraints the API validates a config's output_fields against.
OUTPUT_FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_TRUE_STRINGS = frozenset({"true", "yes", "y", "1"})
_FALSE_STRINGS = frozenset({"false", "no", "n", "0"})

# Per-call token bounds, both directions. A configured input_fields value can be an arbitrarily
# large payload field (e.g. tagsV2, funding.investors), so without these a single company's
# payload sets the bill for the whole run.
MAX_INPUT_COLUMNS = 40
MAX_INPUT_VALUE_CHARS = 4000
MAX_INPUT_LIST_ITEMS = 50
# The per-value bounds above compose multiplicatively (columns x list items x nested dict keys),
# so this is the one check that actually maps to spend: the serialized total.
MAX_INPUT_TOTAL_CHARS = 60000
# Past this nesting level, _bounded/to_domain stop recursing: deeply nested provider JSON would
# otherwise risk RecursionError inside the worker, which tenacity would then retry at full cost.
MAX_INPUT_DEPTH = 6
# A verdict is a handful of short keys, but on a reasoning model this budget also covers the
# reasoning tokens, which are invisible in the reply and can consume it entirely. It's a cap and
# not a reservation, so the headroom is free.
MAX_OUTPUT_TOKENS = 4000

# Bounds on the prompt config's own authored content (prompt_text, output_fields) - not the
# archived payload data above. Defined here, not in ai_enrichment_serializers.py, so any other
# consumer of EnrichmentPromptConfig content (e.g. the admin form) can share the same numbers
# instead of drifting to its own.
MAX_PROMPT_TEXT_CHARS = 20_000
MAX_OUTPUT_FIELDS = 20
MAX_OUTPUT_FIELD_DESCRIPTION_CHARS = 400

_TRUNCATED_AT_MAX_DEPTH = "…(truncated: exceeded max input nesting depth)"


class OutputParseError(ValueError):
    """The model's reply didn't satisfy the config's output schema. Deterministic: retrying the
    same prompt against the same config produces the same failure, so it is not retried."""


class PromptConfigError(ValueError):
    """The stored config's output schema is malformed. Deterministic and operator-fixable, not a
    model-reply problem, so it is raised before any LLM call rather than retried. This module
    stays free of the management-command layer (see the module docstring), so callers that need a
    CLI-style CommandError translate this at their own boundary."""


def verdict_field_key(config: EnrichmentPromptConfig) -> str | None:
    """Which output key represents pass/fail for unknown/summary accounting (the batch runner,
    the dry-run command): the first boolean-typed output field. None if the schema has no
    boolean field at all. Never config.name - the label is a human name, not a data key."""
    for field in config.output_fields:
        if field.get("type") == "boolean":
            return cast(str, field["key"])
    return None


_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def to_domain(value: Any, depth: int = 0) -> Any:
    """Reduce a value that is an email address end to end to its domain, at any depth.

    Applied to every value on its way to the prompt, because the values also land in
    EnrichmentLabelResult.inputs and stay there: a provider field that happens to hold a personal
    address would otherwise be stored indefinitely. The local part carries no classification
    signal anyway - only the company domain does.

    Only a full string match on the email shape reduces - a merely-contains-"@" check would mangle
    free text like "we build AI @scale" or "contact hello@acme.com for a demo" beyond recognition.

    Recurses because the values are not all scalars: tagsV2 and funding.investors are lists, so a
    top-level-only check leaves nested addresses through. depth caps that recursion so a
    pathologically nested payload can't raise RecursionError.
    """
    if depth >= MAX_INPUT_DEPTH:
        return _TRUNCATED_AT_MAX_DEPTH
    if isinstance(value, str):
        return value.rsplit("@", 1)[1].lower() if _EMAIL_RE.fullmatch(value) else value
    if isinstance(value, dict):
        return {key: to_domain(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [to_domain(item, depth + 1) for item in value]
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
        # Stated rather than left implicit: a value outside the range is rejected, and asking for
        # it without saying so is how a config that wants 0-100 fails every row.
        + (f", between {rng[0]} and {rng[1]}" if (rng := field_range(field)) else "")
        + (f", meaning: {field['description']}" if field.get("description") else "")
        + ")"
        for field in config.output_fields
    )
    return f"a JSON object with exactly these keys: {fields_desc}."


def _bounded(value: Any, depth: int = 0) -> Any:
    """Cap a single value's contribution to the prompt. An input_fields value can be an
    arbitrarily long string or list (e.g. description, tagsV2), and one company payload with a
    200 KB description would otherwise set the bill for the whole run.

    Recurses for the same reason to_domain does: several provider fields hold lists of objects, so
    capping only the top level lets an oversized nested string through to the prompt and into the
    stored inputs. depth caps that recursion so a pathologically nested payload can't raise
    RecursionError; past it we return a placeholder instead of descending further.
    """
    if depth >= MAX_INPUT_DEPTH:
        return _TRUNCATED_AT_MAX_DEPTH
    if isinstance(value, str):
        return value[:MAX_INPUT_VALUE_CHARS] + "…" if len(value) > MAX_INPUT_VALUE_CHARS else value
    if isinstance(value, dict):
        return {key: _bounded(item, depth + 1) for key, item in list(value.items())[:MAX_INPUT_LIST_ITEMS]}
    if isinstance(value, list):
        return [_bounded(item, depth + 1) for item in value[:MAX_INPUT_LIST_ITEMS]]
    return value


def bound_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Cap what one company can contribute, in both directions.

    Applied once, before the prompt is built, so the same dict is what the model sees and what
    EnrichmentLabelResult.inputs stores. Bounding inside build_messages instead would leave the
    stored record claiming an untruncated value was sent.

    The per-value bounding above composes multiplicatively (columns x list items x nested dict
    keys), so it caps nothing on its own - the serialized-size check below is the one bound that
    actually maps to spend, and drops trailing columns until the whole payload fits.
    """
    bounded = {key: _bounded(value) for key, value in list(inputs.items())[:MAX_INPUT_COLUMNS]}
    while bounded and len(json.dumps(bounded)) > MAX_INPUT_TOTAL_CHARS:
        bounded.popitem()
    return bounded


def bounding_report(original: dict[str, Any], bounded: dict[str, Any]) -> dict[str, list[str]]:
    """Which columns bound_inputs altered, for meta.bounded.

    Only strings carry a visible "…" once truncated; a dropped column and a shortened list leave
    no trace at all, so a stored tagsV2 of exactly MAX_INPUT_LIST_ITEMS reads identically to a
    truncated one. inputs is the durable record of what the model saw, so anyone re-scoring a
    verdict needs to know the record is partial.

    Compares the two dicts rather than instrumenting the recursion: dropped keys are an exact set
    difference, and a surviving column that serializes shorter was capped somewhere inside it.
    """
    dropped = [key for key in original if key not in bounded]
    truncated = [key for key, value in bounded.items() if len(json.dumps(value)) != len(json.dumps(original[key]))]
    report: dict[str, list[str]] = {}
    if dropped:
        report["dropped"] = dropped
    if truncated:
        report["truncated"] = truncated
    return report


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


def _coerce_str(value: Any) -> str:
    """None and list/dict are rejected rather than stringified: `str(None)` and a list/dict's repr
    are both indistinguishable from a model that genuinely wrote "None" or a Python literal, which
    is exactly the fail-silent outcome _coerce_bool was hardened against for booleans."""
    if value is None or isinstance(value, list | dict):
        raise OutputParseError(f"{value!r} is not a string-coercible scalar")
    return str(value)


_OUTPUT_FIELD_COERCERS: dict[str, Callable[[Any], Any]] = {
    "boolean": _coerce_bool,
    "number": _coerce_number,
    "string": _coerce_str,
}

# Derived from the coercer table so the API can never accept a type this module has no coercer for.
OUTPUT_FIELD_TYPES = tuple(_OUTPUT_FIELD_COERCERS)

# Default range for these keys when a field declares no explicit min/max, so configs written
# before ranges were expressible keep their old behavior.
_UNIT_INTERVAL_KEYS = frozenset({"confidence"})


def field_range(field: dict[str, Any]) -> tuple[float, float] | None:
    """The declared numeric range for an output field, or the legacy key-name default."""
    if field.get("min") is not None and field.get("max") is not None:
        return float(field["min"]), float(field["max"])
    return (0.0, 1.0) if field.get("key") in _UNIT_INTERVAL_KEYS else None


def validate_input_fields(config: EnrichmentPromptConfig) -> None:
    """More input_fields than bound_inputs will carry means the tail is dropped from both the
    prompt and the stored record, with nothing in either to say so. Refusing the config is the
    only point where that's still fixable."""
    if len(config.input_fields) > MAX_INPUT_COLUMNS:
        raise PromptConfigError(
            f"enrichment config declares {len(config.input_fields)} input fields, "
            f"more than the {MAX_INPUT_COLUMNS} that reach the prompt"
        )


def validate_output_fields(config: EnrichmentPromptConfig) -> None:
    """Checked once, before any LLM call: a config typo or omission is deterministic per org, so
    without this it would only surface after paying for a call, and then get retried three times
    against a schema it could never satisfy - the exact amplification the retry predicate on
    OutputParseError exists to prevent. Raises PromptConfigError, not OutputParseError, since this
    is a config problem, not a model reply problem."""
    for field in config.output_fields:
        key = field.get("key")
        field_type = field.get("type")
        if not key or not field_type:
            raise PromptConfigError(f"enrichment output field {field!r} is missing a 'key' or 'type'")
        if key in RESERVED_OUTPUT_FIELD_KEYS:
            raise PromptConfigError(
                f"enrichment output field {key!r} shadows a reserved key {sorted(RESERVED_OUTPUT_FIELD_KEYS)}"
            )
        if field_type not in _OUTPUT_FIELD_COERCERS:
            raise PromptConfigError(f"enrichment output field {key!r} has unknown type {field_type!r}")
        if (field.get("min") is None) != (field.get("max") is None):
            raise PromptConfigError(f"enrichment output field {key!r} declares only one of 'min' and 'max'")
        if field.get("min") is not None:
            if field_type != "number":
                raise PromptConfigError(f"enrichment output field {key!r} has a range but is not a number")
            try:
                low, high = float(field["min"]), float(field["max"])
            except (TypeError, ValueError) as e:
                raise PromptConfigError(f"enrichment output field {key!r} has a non-numeric range") from e
            if low > high:
                raise PromptConfigError(f"enrichment output field {key!r} has min {low} above max {high}")


def _parse_custom_output(config: EnrichmentPromptConfig, data: dict[str, Any]) -> dict[str, Any]:
    """Validate presence and coerce basic types for a configurable output schema — the stored
    output ends up with exactly the configured keys, nothing more.

    validate_output_fields already runs before any of this, so field/type shape is guaranteed —
    the .get() lookup here is belt-and-braces, not the primary line of defence.
    """
    output: dict[str, Any] = {}
    for field in config.output_fields:
        key = field["key"]
        if key not in data:
            raise OutputParseError(f"LLM response is missing the {key!r} key")
        coercer = _OUTPUT_FIELD_COERCERS.get(field.get("type"))
        if coercer is None:
            raise OutputParseError(f"LLM response key {key!r} has unrecognized output type {field.get('type')!r}")
        allowed = field_range(field)
        try:
            value = coercer(data[key])
            # Bare message: the except clause below owns the "LLM response key ..." prefix.
            if allowed is not None and not allowed[0] <= value <= allowed[1]:
                raise OutputParseError(f"{value} is outside the {allowed[0]}-{allowed[1]} range")
        except OutputParseError as e:
            raise OutputParseError(f"LLM response key {key!r}: {e}") from e
        except (TypeError, ValueError) as e:
            raise OutputParseError(f"LLM response key {key!r} could not be coerced to {field['type']}: {e}") from e
        output[key] = value
    return output


@retry(
    # Allowlist, not a blacklist: only failures that can plausibly succeed on a retry earn one.
    # APIConnectionError covers its APITimeoutError subclass too. Everything else — most
    # importantly AuthenticationError and OutputParseError — fails identically on every attempt,
    # so retrying it just triples the spend for the same outcome. This also stops tenacity's
    # three attempts from stacking with the SDK's own retries on a hard failure like a bad
    # gateway credential; see max_retries=0 at every client construction site for the other half
    # of that fix.
    retry=retry_if_exception_type((APIConnectionError, RateLimitError, InternalServerError)),
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
        # Not max_tokens: the OpenAI API rejects it for gpt-5 and o-series models, and config.model
        # is an operator-editable row so the family isn't known here. The gateway's litellm
        # normalizes this one for every route it serves, including Anthropic's native max_tokens.
        max_completion_tokens=MAX_OUTPUT_TOKENS,
        timeout=60,
    )
    # Content filtering and some upstream routes reply with an empty choices list; indexing it
    # unguarded raises IndexError, which (unlike OutputParseError) tenacity retries at full cost
    # for a response shape that will not change.
    if not response.choices:
        raise OutputParseError("LLM response had no choices (likely content filtering)")
    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise OutputParseError("response truncated at max_completion_tokens")
    # Shared with the other products that talk to the gateway: response_format isn't reliably
    # honored on the Anthropic route, so the reply can arrive fenced or wrapped in prose.
    data = extract_json_object(choice.message.content or "")
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
    choices = getattr(response, "choices", None)
    finish_reason = getattr(choices[0], "finish_reason", None) if choices else None
    if isinstance(finish_reason, str):
        meta["finish_reason"] = finish_reason
    return meta


def unknown_output(config: EnrichmentPromptConfig, signup_domain: str | None, reason: str) -> dict[str, Any]:
    """Only the configured keys, same as a real call: why the run was skipped goes in meta, which
    is reserved for provenance, because a schema need not have a "reasoning" key. Public: besides
    classify_payload's own short-circuits below, enrichment/lab.py's classify_fetch_for_run calls
    this directly for its own consent-revoked-mid-run short-circuit, which must never reach
    classify_payload (and therefore the LLM) in the first place.
    """
    output: dict[str, Any] = {}
    verdict_key = verdict_field_key(config)
    if verdict_key is not None:
        output[verdict_key] = UNKNOWN
    output["meta"] = {"skipped": reason}
    output["inputs"] = {"signup_domain": signup_domain, "fields": {}}
    return output


def is_unknown_output(output: dict[str, Any]) -> bool:
    """The authoritative "was this skipped" marker for accounting. verdict_field_key can be None
    (a schema with no boolean field), in which case unknown_output writes no verdict key at all -
    so callers that count unknowns by checking a verdict key miss every skipped row under such a
    schema. meta.skipped is set on every unknown_output call regardless of schema shape."""
    return bool(output.get("meta", {}).get("skipped"))


def classify_payload(
    config: EnrichmentPromptConfig, payload: dict[str, Any] | None, signup_domain: str | None, client: OpenAI
) -> dict[str, Any]:
    validate_input_fields(config)
    validate_output_fields(config)
    # Not-found fetches archive core.py's _MISS_PAYLOAD ({"companyFound": False}); that's
    # evidence of absence, not a thin signal to guess from, so skip the LLM entirely.
    if not payload or payload.get("companyFound") is False:
        return unknown_output(config, signup_domain, "missing or empty archived payload")

    # Checked after resolving, not before: a payload that's present but has none of the configured
    # paths would otherwise bill a call to ask the model about "Company data: {}".
    extracted = extract_input_fields(payload, config.input_fields)
    inputs = bound_inputs(extracted)
    if not inputs:
        return unknown_output(config, signup_domain, "archived payload has none of the configured input fields")

    messages = build_messages(config, inputs, signup_domain)
    output, meta = _call_and_parse(config, messages, client)
    output["inputs"] = {"signup_domain": signup_domain, "fields": inputs}
    bounded = bounding_report(extracted, inputs)
    if bounded:
        meta["bounded"] = bounded
    if meta:
        output["meta"] = meta
    return output


_HOSTNAME_RE = re.compile(r"[a-z0-9.-]+\.[a-z]{2,}")


def ai_processing_approved(organization_id: Any) -> bool:
    """Whether this org allows its data to be sent to an LLM, read fresh rather than off an
    Organization loaded earlier.

    A full-archive run spans hours, so an admin revoking consent partway through must be honored
    for every org still queued, not just the ones enumerated after the change. Only an explicit
    True approves: the column is nullable, and the rest of the codebase treats unset as unapproved
    (posthog/temporal/ai/sync_vectors.py).
    """
    return Organization.objects.filter(pk=organization_id, is_ai_data_processing_approved=True).exists()


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
    domain = membership.user.email.rsplit("@", 1)[1].lower()
    # User.email is only validated through full_clean()/serializers, so rows written by
    # createsuperuser, imports, or backfills can hold anything after the "@" - and this domain is
    # interpolated into the system prompt's highest-trust segment via build_messages.
    return domain if _HOSTNAME_RE.fullmatch(domain) else None


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
