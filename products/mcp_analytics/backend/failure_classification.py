"""Classify MCP tool-call failure messages into a fixed set of causes.

Staff-tool support code for ``classify_mcp_failures``: normalizes raw error messages into
fingerprints (pure, no LLM) and classifies fingerprints in batches via an LLM call, mirroring the
pattern in ``intent_generation.py``.
"""

import re
from enum import StrEnum

from django.conf import settings

import openai
import structlog
import posthoganalytics
from posthoganalytics.ai.openai import OpenAI
from pydantic import BaseModel, ValidationError

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


class FailureClassificationUnavailable(RuntimeError):
    pass


FAILURE_CLASS_MODEL = "gpt-5.6-luna"
CLASSIFY_BATCH_SIZE = 25
FINGERPRINT_MAX_CHARS = 200
_QUOTED_VALUE_MAX_CHARS = 80


class FailureClass(StrEnum):
    INPUT_SCHEMA_MISMATCH = "input_schema_mismatch"
    OUTPUT_SCHEMA_VIOLATION = "output_schema_violation"
    UNKNOWN_TOOL = "unknown_tool"
    TIMEOUT = "timeout"
    UPSTREAM_5XX = "upstream_5xx"
    TRANSPORT_FAILURE = "transport_failure"
    RESOURCE_NOT_FOUND = "resource_not_found"
    EMPTY_RESULT_AS_ERROR = "empty_result_as_error"
    STATE_CONFLICT = "state_conflict"
    MISSING_PRECONDITION = "missing_precondition"
    AUTH_OR_PERMISSION = "auth_or_permission"
    ENTITLEMENT_GAP = "entitlement_gap"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"


FAILURE_CLASSES: tuple[str, ...] = tuple(cls.value for cls in FailureClass)

_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_URL_RE = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
_ISO_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?)?\b", re.IGNORECASE
)
_DOUBLE_QUOTED_RE = re.compile(rf'"[^"]{{0,{_QUOTED_VALUE_MAX_CHARS}}}"')
_SINGLE_QUOTED_RE = re.compile(rf"'[^']{{0,{_QUOTED_VALUE_MAX_CHARS}}}'")
_NUMBER_RE = re.compile(r"\d+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_fingerprint(msg: str) -> str:
    """Collapse a raw error message into a stable fingerprint for grouping.

    Strips values that vary per-occurrence (IDs, timestamps, quoted literals, numbers) but leaves
    the message's language and wording untouched — a translated message must stay a distinct
    fingerprint from its English twin, since fingerprinting is grouping, not classification.
    """
    normalized = msg.lower()
    normalized = _URL_RE.sub(" ", normalized)
    normalized = _EMAIL_RE.sub(" ", normalized)
    normalized = _UUID_RE.sub(" ", normalized)
    normalized = _ISO_DATE_RE.sub(" ", normalized)
    normalized = _DOUBLE_QUOTED_RE.sub(" ", normalized)
    normalized = _SINGLE_QUOTED_RE.sub(" ", normalized)
    normalized = _NUMBER_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized[:FINGERPRINT_MAX_CHARS]


SYSTEM_PROMPT = f"""You classify MCP tool-call failure messages into exactly one of these {len(FAILURE_CLASSES)} \
classes:

- input_schema_mismatch: caller's arguments rejected against the tool's declared input contract \
— "Invalid arguments: expected array, received undefined", "The <field> field is required"
- output_schema_violation: the server's own response violates its declared output schema — \
"Output validation error: invalid structured content"
- unknown_tool: a tool that doesn't exist was called — "Unknown tool: <name>", JSON-RPC -32601
- timeout: the operation ran out of time — "timed out after 45s"
- upstream_5xx: a dependency behind the server failed — "API request failed: 503"
- transport_failure: network-level failure — "fetch failed", "connection reset"
- resource_not_found: the referenced entity doesn't exist — "Resource does not exist — verify the ID"
- empty_result_as_error: a search legitimately found nothing but was surfaced as an error — "No \
matching records found; adjust your query"
- state_conflict: entity exists but its current state forbids the operation — "already exists", \
"not in draft status"
- missing_precondition: one-time setup never done — "no account connected", "sender email must \
be verified"
- auth_or_permission: identity/credential/scope problem — 401/403, "insufficient scopes", \
"read-only key"
- entitlement_gap: authentication fine, the caller's plan doesn't include this — "not available \
on the free tier", "upgrade your plan"
- rate_limited: throttled on volume/speed — 429, "retry after N seconds"
- internal_error: the message carries no diagnosable cause — "tool failed", "[object Object]", \
bare stack fragments

Boundary rules:
1. Trust the message over the JSON-RPC code: "-32602: Tool X not found" is unknown_tool; \
"-32602: Output validation error" is output_schema_violation.
2. 429 + "upgrade your plan" is entitlement_gap, not rate_limited. "Retry after N seconds" is \
rate_limited.
3. 403 + "requires premium/subscription" is entitlement_gap, not auth_or_permission.
4. missing_precondition vs state_conflict: would retrying tomorrow with no setup action still \
fail? Yes = missing_precondition; depends on a live entity's current state = state_conflict.
5. resource_not_found vs empty_result_as_error: lookup by identifier that missed = \
resource_not_found; search/filter with zero rows = empty_result_as_error.
6. "The X field is required" at call time is input_schema_mismatch unless the requirement is \
business-conditional.
7. Language is irrelevant: a translated message classifies the same as its English twin.
8. A field's NAME never picks the class ("timeout seconds field must not be greater than 25" is \
input_schema_mismatch, not timeout).
9. If the message carries an upsell anywhere ("here are your options", plan limits), \
entitlement_gap wins. If genuinely no cause is recoverable, internal_error — never guess.

Each input line is numbered. Return exactly one classification per input line, in the same order, \
as JSON of exactly this shape:
{{"classifications": [{{"line_number": 1, "failure_class": "<one of the 14 class names>"}}, ...]}}"""

# The LLM reads the raw representative message, never the normalized fingerprint: normalization
# strips numbers, so the status and JSON-RPC codes the boundary rules pivot on (429, 403, -32601)
# would be gone before classification. The fingerprint is only the grouping/cache key.
MESSAGE_MAX_CHARS = 400


class FingerprintClassification(BaseModel):
    line_number: int
    failure_class: FailureClass


class ClassificationBatch(BaseModel):
    classifications: list[FingerprintClassification]


def _build_batch_prompt(messages: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {message[:MESSAGE_MAX_CHARS]}" for i, message in enumerate(messages))
    return f"Failure messages:\n{numbered}"


def _call_llm(client: OpenAI, messages: list[str], team: Team) -> ClassificationBatch:
    response = client.chat.completions.create(
        model=FAILURE_CLASS_MODEL,
        temperature=0,
        timeout=30,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_batch_prompt(messages)},
        ],
        response_format={"type": "json_object"},
        user=f"team/{team.id}/mcp-analytics-failure-classifier",
        posthog_properties={"ai_product": "mcp_analytics", "ai_feature": "failure-classification"},
    )
    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise ValueError("LLM returned an empty classification response")
    return ClassificationBatch.model_validate_json(content)


def _classify_batch(client: OpenAI, batch: list[tuple[str, str]], team: Team) -> dict[str, str]:
    """Classify one (fingerprint, message) batch, retrying once on a malformed or invalid-class response."""
    messages = [message for _, message in batch]
    for attempt in range(2):
        try:
            parsed = _call_llm(client, messages, team)
        except (openai.OpenAIError, ValidationError, ValueError):
            if attempt == 1:
                break
            continue
        # Valid JSON with missing/duplicate/out-of-range line numbers is as malformed as a
        # schema violation: it must consume the retry, not silently orphan inputs.
        returned_lines = sorted(item.line_number for item in parsed.classifications)
        if returned_lines != list(range(1, len(batch) + 1)):
            if attempt == 1:
                break
            continue
        by_line = {item.line_number: item.failure_class.value for item in parsed.classifications}
        return {fingerprint: by_line[i + 1] for i, (fingerprint, _) in enumerate(batch)}
    logger.warning("mcp_analytics.failure_classifier.batch_failed", team_id=team.id, batch_size=len(batch))
    return dict.fromkeys((fingerprint for fingerprint, _ in batch), FailureClass.INTERNAL_ERROR.value)


def classify_fingerprints(messages_by_fingerprint: dict[str, str], team: Team) -> dict[str, str]:
    """Classify each fingerprint into one of the 14 failure classes via batched LLM calls.

    ``messages_by_fingerprint`` maps each fingerprint to its representative raw message — the LLM
    reads the message (see the note above ``MESSAGE_MAX_CHARS``), the fingerprint keys the result.
    One call per batch of ``CLASSIFY_BATCH_SIZE``. A batch that fails validation is retried once;
    if it still fails, every fingerprint in that batch is marked ``internal_error`` rather than
    left unclassified.
    """
    if not messages_by_fingerprint:
        return {}

    # Failure messages are customer-authored text, so shipping them to the LLM needs the
    # organization's AI data processing consent, same as intent generation.
    if not team.organization.is_ai_data_processing_approved:
        raise FailureClassificationUnavailable("AI data processing is not approved for this organization")

    client = OpenAI(posthog_client=posthoganalytics.default_client, base_url=settings.OPENAI_BASE_URL)
    items = list(messages_by_fingerprint.items())
    result: dict[str, str] = {}
    with tags_context(
        product=Product.MCP_ANALYTICS, feature=Feature.QUERY, team_id=team.id, name="mcp_analytics_failure_classifier"
    ):
        for start in range(0, len(items), CLASSIFY_BATCH_SIZE):
            result.update(_classify_batch(client, items[start : start + CLASSIFY_BATCH_SIZE], team))
    return result
