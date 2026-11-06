"""Generate, store and read the model-written summary of an issue.

The issue-created workflow calls `generate_issue_summary_from_event`, which writes the only summary an issue gets.
A read calls `read_issue_summary`, which returns what is stored and never starts generation.
"""

import re
import json
import time
import hashlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from django.db import IntegrityError
from django.utils import timezone

import structlog
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema
from prometheus_client import Counter, Histogram
from pydantic import ValidationError
from redis.exceptions import RedisError

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import build_openai_client, resolve_ai_gateway_config, team_distinct_id
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.models import Team, User
from posthog.ph_client import ph_background_capture
from posthog.redis import get_client
from posthog.token_bucket import BucketDecision, BucketUnavailable, consume, peek, refund
from posthog.utils import get_instance_region

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.contracts import UserNotOrganizationMemberError
from products.error_tracking.backend.facade.contracts import IssueSummaryStatus, IssueSummaryUnavailableReason
from products.error_tracking.backend.facade.query_utils import as_record, extract_release, to_number, truncate_text
from products.error_tracking.backend.logic.issue_summary_config import (
    ISSUE_SUMMARY_FLAG,
    ISSUE_SUMMARY_LLM_TIMEOUT_SECONDS,
    ISSUE_SUMMARY_LOCK_TTL_SECONDS,
    ISSUE_SUMMARY_MAX_OUTPUT_TOKENS,
    ISSUE_SUMMARY_MODEL,
    ISSUE_SUMMARY_ON_WRITE_FLAG,
    ISSUE_SUMMARY_STACKTRACE_MAX_TOKENS,
    ISSUE_SUMMARY_WRITE_BUDGET,
)
from products.error_tracking.backend.logic.issue_summary_prompt import (
    ISSUE_SUMMARY_IMPACT_LINE,
    ISSUE_SUMMARY_IMPACT_NOT_KNOWN_YET,
    ISSUE_SUMMARY_INPUT_TEMPLATE,
    ISSUE_SUMMARY_PROMPT_VERSION,
    ISSUE_SUMMARY_SYSTEM_PROMPT,
    IssueSummaryResponse,
)
from products.error_tracking.backend.logic.severity_inference import (
    first_exception,
    mechanism_handled,
    page_without_query,
)
from products.error_tracking.backend.logic.team_flags import team_flag_enabled
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueSummary,
)
from products.error_tracking.backend.temporal.lifecycle.rendering import render_stacktrace

logger = structlog.get_logger(__name__)

ISSUE_SUMMARY_WRITE_BUDGET_KEY_PREFIX = "error_tracking_issue_summary_write"
ISSUE_SUMMARY_LOCK_KEY_PREFIX = "error_tracking_issue_summary_lock"
ISSUE_SUMMARY_AI_PRODUCT = "error_tracking"
ISSUE_SUMMARY_TASK_EVENT = "error_tracking_issue_summary_generation"
# The Go gateway keeps the prompt and the reply out of the AI observability project when this is set.
PRIVACY_MODE_HEADER = "X-PostHog-Privacy-Mode"

UNKNOWN = "unknown"
IN_APP_FRAME_MARKER = "[in-app]"
# Event values must not open or close the <issue> block that fences them in the prompt. Every angle bracket
# becomes a look-alike, so no "<" from event text reaches the prompt and no nesting can rebuild a fence tag.
FENCE_ESCAPES = str.maketrans({"<": "\u2039", ">": "\u203a"})
# A summary holds no URL and no shell command, even one the prompt holds, because the event text is attacker-controlled.
SUMMARY_URL = re.compile(r"\b(?:[a-z][a-z0-9+.-]*://|www\.)\S", re.IGNORECASE)
SUMMARY_SHELL_COMMAND = re.compile(
    r"\|\s*(?:sudo\s+)?(?:(?:ba|z|da|k)?sh|iex|python[\d.]*|node|perl|ruby)\b"
    r"|\b(?:curl|wget)\s+(?:-|\S+://|\S+\.\S)"
    r"|\b(?:ba|z|da|k)?sh\s+-[a-z]*c\b"
    r"|\b(?:python[\d.]*|node|perl|ruby)\s+-[a-z]*[ce]\b"
    r"|\bbase64\s+(?:-d|--decode)\b"
    r"|\bsudo\s+\S"
    r"|\brm\s+-[a-z]*[rf]"
    r"|\bchmod\s+\+?[0-7x]"
    r"|\b(?:powershell|pwsh)(?:\.exe)?\s+-"
    r"|\bInvoke-Expression\b",
    re.IGNORECASE,
)
# A worker claims with its own token, so only that worker can release the claim.
LOCK_CLAIM_PREFIX = "claim:"
# Deletes the key only while it holds ARGV[1], so a claim another worker took after this one expired survives.
RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class IssueSummaryTrigger(StrEnum):
    WRITE = "write"


class IssueSummaryOutcome(StrEnum):
    GENERATED = "generated"
    # A summary is already stored.
    FRESH = "fresh"
    DISABLED = "disabled"
    AI_NOT_APPROVED = "ai_not_approved"
    IN_PROGRESS = "in_progress"
    ISSUE_MISSING = "issue_missing"
    NO_EXCEPTION = "no_exception"
    INPUTS_ERROR = "inputs_error"
    RATE_LIMITED = "rate_limited"
    GATEWAY_UNCONFIGURED = "gateway_unconfigured"
    MODEL_ERROR = "model_error"
    INVALID_OUTPUT = "invalid_output"
    UNEXPECTED_ERROR = "unexpected_error"


ISSUE_SUMMARY_OUTCOMES = Counter(
    "error_tracking_issue_summary_total",
    "Issue summary requests by outcome and trigger",
    labelnames=("outcome", "trigger"),
)

ISSUE_SUMMARY_STAGE_SECONDS = Histogram(
    "error_tracking_issue_summary_stage_seconds",
    "Time spent in each issue summary generation stage",
    labelnames=("stage",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 6, 8, 12, 20, 30, 60, 120),
)


class IssueSummaryTimings:
    """Milliseconds per generation stage, keyed `<stage>_ms`. A stage that did not run has no entry.

    Stages nest, so do not add them up: `total` contains every other stage.
    """

    def __init__(self) -> None:
        self.ms: dict[str, int] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.monotonic()
        try:
            yield
        finally:
            self.record(name, time.monotonic() - started)

    def record(self, name: str, seconds: float) -> None:
        self.ms[f"{name}_ms"] = round(seconds * 1000)
        ISSUE_SUMMARY_STAGE_SECONDS.labels(stage=name).observe(seconds)


@frozen
class IssueSummaryResult:
    outcome: IssueSummaryOutcome
    # The new summary, or the stored one when no new one was generated.
    summary: ErrorTrackingIssueSummary | None


@frozen
class IssueSummaryInputs:
    prompt: str
    input_hash: str


@frozen
class IssueSummaryState:
    status: IssueSummaryStatus
    summary: ErrorTrackingIssueSummary | None = None
    reason: IssueSummaryUnavailableReason | None = None


class WorkflowEventUnavailable(Exception):
    """The workflow's event did not load, often because ClickHouse has not ingested it yet.

    It is not an inputs error, so the activity raises and Temporal retries it.
    """


def issue_summaries_enabled(team_id: int) -> bool:
    return team_flag_enabled(ISSUE_SUMMARY_FLAG, team_id)


def issue_summaries_on_write_enabled(team_id: int) -> bool:
    return team_flag_enabled(ISSUE_SUMMARY_ON_WRITE_FLAG, team_id)


def summary_sources_readable(team_id: int, user: User) -> bool:
    """False when the user may not read an event property the summary is written from.

    One summary serves the whole team, so a user with a property restriction could otherwise read it through the summary.
    """
    try:
        restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
    except UserNotOrganizationMemberError:
        return False
    return ISSUE_SUMMARY_SOURCE_PROPERTIES.isdisjoint(split_restricted_property_names(restrictions).event)


def is_ai_data_processing_approved(team_id: int) -> bool:
    """Fail closed when the team or its organization is missing."""
    return bool(
        Team.objects.filter(id=team_id).values_list("organization__is_ai_data_processing_approved", flat=True).first()
    )


def get_issue_summary(team_id: int, issue_id: UUID | str) -> ErrorTrackingIssueSummary | None:
    return ErrorTrackingIssueSummary.objects.for_team(team_id).filter(issue_id=issue_id).first()


def read_issue_summary(team_id: int, issue_id: UUID | str, user: User) -> IssueSummaryState:
    """The stored summary, or the reason none is shown. Never starts generation."""
    if not issue_summaries_enabled(team_id):
        return IssueSummaryState(status=IssueSummaryStatus.UNAVAILABLE, reason=IssueSummaryUnavailableReason.DISABLED)
    if not summary_sources_readable(team_id, user):
        return IssueSummaryState(status=IssueSummaryStatus.UNAVAILABLE, reason=IssueSummaryUnavailableReason.RESTRICTED)
    if not is_ai_data_processing_approved(team_id):
        return IssueSummaryState(
            status=IssueSummaryStatus.UNAVAILABLE, reason=IssueSummaryUnavailableReason.AI_NOT_APPROVED
        )
    stored = get_issue_summary(team_id, issue_id)
    if stored is not None:
        return IssueSummaryState(status=IssueSummaryStatus.READY, summary=stored)
    return IssueSummaryState(status=IssueSummaryStatus.NOT_GENERATED)


def generation_blocked(team_id: int, stored: ErrorTrackingIssueSummary | None) -> IssueSummaryOutcome | None:
    """The reason no generation can start now, or None when one can."""
    # Generation sees only the first event, so any stored summary already covers it.
    if stored is not None:
        return IssueSummaryOutcome.FRESH
    if not issue_summaries_enabled(team_id):
        return IssueSummaryOutcome.DISABLED
    if not is_ai_data_processing_approved(team_id):
        return IssueSummaryOutcome.AI_NOT_APPROVED
    return None


def generate_issue_summary_from_event(
    team_id: int, issue_id: UUID | str, load_event_properties: Callable[[Team], dict[str, object]]
) -> IssueSummaryResult:
    """Generate the summary of a new issue from its first event, with no ClickHouse query.

    Does nothing when a summary is already stored.
    `load_event_properties` runs only after every check passes, so a blocked attempt reads no event.
    """
    trigger = IssueSummaryTrigger.WRITE
    timings = IssueSummaryTimings()
    try:
        with timings.stage("total"):
            result = _get_or_generate(team_id, issue_id, load_event_properties, timings)
    except Exception:
        ISSUE_SUMMARY_OUTCOMES.labels(outcome=IssueSummaryOutcome.UNEXPECTED_ERROR.value, trigger=trigger.value).inc()
        _report_task(
            team_id, issue_id, trigger, IssueSummaryOutcome.UNEXPECTED_ERROR, has_summary=False, timings=timings
        )
        raise
    ISSUE_SUMMARY_OUTCOMES.labels(outcome=result.outcome.value, trigger=trigger.value).inc()
    logger.info(
        "error_tracking_issue_summary",
        team_id=team_id,
        issue_id=str(issue_id),
        outcome=result.outcome.value,
        trigger=trigger.value,
        has_summary=result.summary is not None,
        **timings.ms,
    )
    _report_task(team_id, issue_id, trigger, result.outcome, has_summary=result.summary is not None, timings=timings)
    return result


def _load_workflow_event(load_event_properties: Callable[[Team], dict[str, object]], team: Team) -> dict[str, object]:
    try:
        return load_event_properties(team)
    except Exception as error:
        raise WorkflowEventUnavailable from error


def report_worker_busy(team_id: int, issue_id: UUID | str, trigger: IssueSummaryTrigger) -> None:
    """Count and report a lifecycle attempt skipped because every worker summary slot was busy."""
    ISSUE_SUMMARY_OUTCOMES.labels(outcome=IssueSummaryOutcome.RATE_LIMITED.value, trigger=trigger.value).inc()
    _report_task(
        team_id, issue_id, trigger, IssueSummaryOutcome.RATE_LIMITED, has_summary=False, timings=IssueSummaryTimings()
    )


def _report_task(
    team_id: int,
    issue_id: UUID | str,
    trigger: IssueSummaryTrigger,
    outcome: IssueSummaryOutcome,
    *,
    has_summary: bool,
    timings: IssueSummaryTimings,
) -> None:
    # The background client sends from its own thread, so the worker takes the next task without waiting for a flush.
    try:
        ph_background_capture()(
            distinct_id=team_distinct_id(team_id),
            event=ISSUE_SUMMARY_TASK_EVENT,
            properties={
                "team_id": team_id,
                "issue_id": str(issue_id),
                # The client's `region` super property names the destination project and overwrites an event `region`.
                "instance_region": get_instance_region(),
                "trigger": trigger.value,
                "outcome": outcome.value,
                "has_summary": has_summary,
                **timings.ms,
            },
        )
    except Exception:
        logger.warning("error_tracking_issue_summary_capture_failed", team_id=team_id, exc_info=True)


def _get_or_generate(
    team_id: int,
    issue_id: UUID | str,
    load_event_properties: Callable[[Team], dict[str, object]],
    timings: IssueSummaryTimings,
) -> IssueSummaryResult:
    stored = get_issue_summary(team_id, issue_id)
    if (blocked := generation_blocked(team_id, stored)) is not None:
        return IssueSummaryResult(outcome=blocked, summary=stored)
    claim = f"{LOCK_CLAIM_PREFIX}{uuid4().hex}"
    if (held := _claim_generation(team_id, issue_id, claim)) is not None:
        return IssueSummaryResult(outcome=held, summary=stored)
    try:
        return _generate_claimed(team_id, issue_id, load_event_properties, timings)
    finally:
        _release_claim(team_id, issue_id, claim)


def _generate_claimed(
    team_id: int,
    issue_id: UUID | str,
    load_event_properties: Callable[[Team], dict[str, object]],
    timings: IssueSummaryTimings,
) -> IssueSummaryResult:
    # Another worker can finish between the first read and the claim.
    if (stored := get_issue_summary(team_id, issue_id)) is not None:
        return IssueSummaryResult(outcome=IssueSummaryOutcome.FRESH, summary=stored)

    budget_key = f"{ISSUE_SUMMARY_WRITE_BUDGET_KEY_PREFIX}:{team_id}"
    budget = ISSUE_SUMMARY_WRITE_BUDGET
    # This read keeps a team with no tokens left from loading the event for every new issue. `consume` still makes
    # the decision. An unavailable bucket fails closed.
    peeked = peek(budget_key, budget)
    if isinstance(peeked, BucketUnavailable) or not peeked.allowed:
        return IssueSummaryResult(outcome=IssueSummaryOutcome.RATE_LIMITED, summary=None)

    team = Team.objects.get(id=team_id)
    try:
        with timings.stage("inputs"):
            inputs = build_issue_summary_inputs_from_event(
                team, issue_id, _load_workflow_event(load_event_properties, team)
            )
    except WorkflowEventUnavailable:
        raise
    except Exception as error:
        capture_exception(error, {"team_id": team_id, "issue_id": str(issue_id)})
        logger.warning("error_tracking_issue_summary_inputs_failed", team_id=team_id, issue_id=str(issue_id))
        return IssueSummaryResult(outcome=IssueSummaryOutcome.INPUTS_ERROR, summary=None)
    if isinstance(inputs, IssueSummaryOutcome):
        return IssueSummaryResult(outcome=inputs, summary=None)

    match consume(budget_key, budget):
        case BucketDecision(allowed=False):
            return IssueSummaryResult(outcome=IssueSummaryOutcome.RATE_LIMITED, summary=None)
        case BucketUnavailable(error=bucket_error):
            logger.warning("error_tracking_issue_summary_budget_unavailable", team_id=team_id, error=bucket_error)
            return IssueSummaryResult(outcome=IssueSummaryOutcome.RATE_LIMITED, summary=None)

    # Only the Go gateway honours privacy mode, so the Python gateway fallback is never used.
    if resolve_ai_gateway_config() is None:
        refund(budget_key, budget)
        return IssueSummaryResult(outcome=IssueSummaryOutcome.GATEWAY_UNCONFIGURED, summary=None)

    try:
        with timings.stage("model"):
            raw = _call_model(team_id, issue_id, inputs.prompt)
    except Exception as error:
        capture_exception(error, {"team_id": team_id, "issue_id": str(issue_id)})
        logger.warning("error_tracking_issue_summary_model_failed", team_id=team_id, issue_id=str(issue_id))
        return IssueSummaryResult(outcome=IssueSummaryOutcome.MODEL_ERROR, summary=None)

    response = parse_summary_response(raw)
    if response is None:
        logger.warning("error_tracking_issue_summary_invalid_output", team_id=team_id, issue_id=str(issue_id))
        return IssueSummaryResult(outcome=IssueSummaryOutcome.INVALID_OUTPUT, summary=None)
    if unsafe_fields := unsafe_summary_fields(response.model_dump()):
        logger.warning(
            "error_tracking_issue_summary_unsafe_output",
            team_id=team_id,
            issue_id=str(issue_id),
            fields=unsafe_fields,
        )
        return IssueSummaryResult(outcome=IssueSummaryOutcome.INVALID_OUTPUT, summary=None)

    generated_at = timezone.now()
    try:
        summary, _ = ErrorTrackingIssueSummary.objects.for_team(team_id).update_or_create(
            issue_id=issue_id,
            defaults={
                "team_id": team_id,
                "content": response.model_dump(),
                "input_hash": inputs.input_hash,
                "model": ISSUE_SUMMARY_MODEL,
                "generated_at": generated_at,
                "checked_at": generated_at,
            },
        )
    except IntegrityError:
        # The issue was merged away or deleted while the model ran.
        return IssueSummaryResult(outcome=IssueSummaryOutcome.ISSUE_MISSING, summary=None)
    return IssueSummaryResult(outcome=IssueSummaryOutcome.GENERATED, summary=summary)


def _lock_key(team_id: int, issue_id: UUID | str) -> str:
    return f"{ISSUE_SUMMARY_LOCK_KEY_PREFIX}:{team_id}:{issue_id}"


def _claim_generation(team_id: int, issue_id: UUID | str, claim: str) -> IssueSummaryOutcome | None:
    """None when this worker now holds the issue under `claim`, else the outcome that stops it."""
    try:
        claimed = get_client().set(_lock_key(team_id, issue_id), claim, nx=True, ex=ISSUE_SUMMARY_LOCK_TTL_SECONDS)
    except RedisError:
        logger.warning("error_tracking_issue_summary_lock_unavailable", team_id=team_id, exc_info=True)
        return IssueSummaryOutcome.RATE_LIMITED
    return None if claimed else IssueSummaryOutcome.IN_PROGRESS


def _release_claim(team_id: int, issue_id: UUID | str, claim: str) -> None:
    try:
        get_client().register_script(RELEASE_LUA)(keys=[_lock_key(team_id, issue_id)], args=[claim])
    except RedisError:
        logger.warning("error_tracking_issue_summary_lock_unavailable", team_id=team_id, exc_info=True)


def compute_input_hash(*, fingerprints: list[str], latest_release: str | None, occurrences: int) -> str:
    payload = {
        "prompt_version": ISSUE_SUMMARY_PROMPT_VERSION,
        "fingerprints": sorted(fingerprints),
        "latest_release": latest_release,
        # floor(log2(n)) + 1, so the hash changes each time the count doubles.
        "occurrence_bucket": max(occurrences, 0).bit_length(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# The only event properties the prompt builder sees, and the ones `summary_sources_readable` checks.
# `_source_properties` drops every other key, so a property left out is missing from the prompt, not leaked.
ISSUE_SUMMARY_SOURCE_PROPERTIES = frozenset(
    {"$exception_list", "$exception_level", "$lib", "$current_url", "$exception_release"}
)


def build_issue_summary_inputs_from_event(
    team: Team, issue_id: UUID | str, event_properties: dict[str, object]
) -> IssueSummaryInputs | IssueSummaryOutcome:
    """Build the inputs of a new issue from its only event, which is both its first and its latest."""
    issue = _issue_with_first_seen(team, issue_id)
    if issue is None:
        return IssueSummaryOutcome.ISSUE_MISSING
    source_properties = _source_properties(event_properties)
    stack_trace = _summary_stack_trace(source_properties)
    if not stack_trace:
        return IssueSummaryOutcome.NO_EXCEPTION
    return _summary_inputs(
        team,
        issue_id,
        first_seen=getattr(issue, "first_seen", None),
        event_properties=source_properties,
        first_event_properties=source_properties,
        stack_trace=stack_trace,
        impact=None,
        trend={},
    )


def _issue_with_first_seen(team: Team, issue_id: UUID | str) -> ErrorTrackingIssue | None:
    return ErrorTrackingIssue.objects.with_first_seen().filter(team_id=team.id, id=issue_id).first()


def _summary_stack_trace(event_properties: dict[str, object]) -> str:
    if not event_properties:
        return ""
    return render_stacktrace(mark_in_app_frames(event_properties), ISSUE_SUMMARY_STACKTRACE_MAX_TOKENS)


def _summary_inputs(
    team: Team,
    issue_id: UUID | str,
    *,
    first_seen: datetime | None,
    event_properties: dict[str, object],
    first_event_properties: dict[str, object],
    stack_trace: str,
    impact: dict[str, object] | None,
    trend: dict[str, object],
) -> IssueSummaryInputs:
    latest_release = extract_release(event_properties).get("version")
    first_release = extract_release(first_event_properties).get("version")
    exception = first_exception(event_properties)
    handled = mechanism_handled(event_properties)

    fields = {
        "exception_type": _text(exception.get("type")),
        "exception_message": _text(truncate_text(exception.get("value"), 500)),
        "handled": UNKNOWN if handled is None else ("yes" if handled else "no"),
        "level": _text(event_properties.get("$exception_level")),
        "lib": _text(event_properties.get("$lib")),
        "url_path": _text(page_without_query(event_properties.get("$current_url"))),
        "stack_trace": stack_trace.rstrip("\n"),
        "first_seen": first_seen.isoformat() if first_seen else UNKNOWN,
        "first_release": _text(first_release),
        "latest_release": _text(latest_release),
        "trend_direction": _text(trend.get("direction")),
        "previous_occurrences": _count(trend.get("previous_occurrences")),
        "current_occurrences": _count(trend.get("current_occurrences")),
        "impact": _impact_line(impact),
    }
    prompt = ISSUE_SUMMARY_INPUT_TEMPLATE.format(
        **{name: value.translate(FENCE_ESCAPES) for name, value in fields.items()}
    )
    fingerprints = list(
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team.id, issue_id=issue_id).values_list(
            "fingerprint", flat=True
        )
    )
    # A new issue holds only its first event, so it hashes as one occurrence.
    occurrences = to_number(impact.get("occurrences")) if impact is not None else 1
    return IssueSummaryInputs(
        prompt=prompt,
        input_hash=compute_input_hash(
            fingerprints=fingerprints,
            latest_release=latest_release if isinstance(latest_release, str) else None,
            occurrences=int(occurrences) if occurrences is not None else 0,
        ),
    )


def mark_in_app_frames(event_properties: dict[str, object]) -> dict[str, object]:
    """Return a copy whose in-app frames render with an `[in-app]` prefix on the function name.

    The shared renderer leaves `in_app` out, and embeddings and severity inference depend on its output.
    """
    exception_list = event_properties.get("$exception_list")
    if not isinstance(exception_list, list):
        return event_properties
    marked: list[object] = []
    for exception in exception_list:
        stacktrace = as_record(exception.get("stacktrace")) if isinstance(exception, dict) else None
        frames = stacktrace.get("frames") if stacktrace else None
        if not isinstance(exception, dict) or stacktrace is None or not isinstance(frames, list):
            marked.append(exception)
            continue
        marked_frames = [_mark_in_app_frame(frame) for frame in frames]
        marked.append({**exception, "stacktrace": {**stacktrace, "frames": marked_frames}})
    return {**event_properties, "$exception_list": marked}


def _mark_in_app_frame(frame: object) -> object:
    if not isinstance(frame, dict) or frame.get("in_app") is not True:
        return frame
    name = frame.get("resolved_name")
    if not isinstance(name, str):
        name = frame.get("mangled_name")
    return {**frame, "resolved_name": f"{IN_APP_FRAME_MARKER} {name if isinstance(name, str) else ''}".rstrip()}


def _text(value: object) -> str:
    return value if isinstance(value, str) and value else UNKNOWN


def _count(value: object) -> str:
    number = to_number(value)
    return str(int(number)) if number is not None else UNKNOWN


def _impact_line(impact: dict[str, object] | None) -> str:
    if impact is None:
        return ISSUE_SUMMARY_IMPACT_NOT_KNOWN_YET
    return ISSUE_SUMMARY_IMPACT_LINE.format(
        occurrences=_count(impact.get("occurrences")),
        users=_count(impact.get("users")),
        sessions=_count(impact.get("sessions")),
    )


def _source_properties(properties: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in properties.items() if key in ISSUE_SUMMARY_SOURCE_PROPERTIES}


ISSUE_SUMMARY_RESPONSE_FORMAT: ResponseFormatJSONSchema = {
    "type": "json_schema",
    "json_schema": {
        "name": "issue_summary",
        "strict": True,
        "schema": IssueSummaryResponse.model_json_schema(),
    },
}


def _call_model(team_id: int, issue_id: UUID | str, prompt: str) -> str:
    client: OpenAI = build_openai_client(
        "django",
        ai_product=ISSUE_SUMMARY_AI_PRODUCT,
        properties={"team_id": str(team_id), "issue_id": str(issue_id)},
        distinct_id=team_distinct_id(team_id),
    )
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": ISSUE_SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    response = client.with_options(max_retries=1).chat.completions.create(
        model=ISSUE_SUMMARY_MODEL,
        messages=messages,
        user=team_distinct_id(team_id),
        timeout=ISSUE_SUMMARY_LLM_TIMEOUT_SECONDS,
        max_completion_tokens=ISSUE_SUMMARY_MAX_OUTPUT_TOKENS,
        response_format=ISSUE_SUMMARY_RESPONSE_FORMAT,
        extra_headers={PRIVACY_MODE_HEADER: "true"},
    )
    return response.choices[0].message.content or ""


def parse_summary_response(raw: str) -> IssueSummaryResponse | None:
    try:
        return IssueSummaryResponse.model_validate_json(raw)
    except ValidationError:
        pass
    # A model behind the Anthropic route can ignore the strict schema and wrap the JSON in prose.
    parsed = extract_json_object(raw)
    if parsed is None:
        return None
    try:
        return IssueSummaryResponse.model_validate(parsed)
    except ValidationError:
        return None


def unsafe_summary_fields(content: Mapping[str, object]) -> list[str]:
    """Return the text fields that hold a URL or a shell command.

    The whole summary is dropped when any field fails: a model that copied one injected instruction may have
    followed others, such as one that calls a real error benign.
    """
    return [
        name
        for name, value in content.items()
        if isinstance(value, str) and (SUMMARY_URL.search(value) or SUMMARY_SHELL_COMMAND.search(value))
    ]
