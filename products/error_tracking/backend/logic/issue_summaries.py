"""Generate, store and read the model-written summary of an issue.

Every trigger calls `get_or_generate_issue_summary`, directly or through the Celery task. It returns
the stored summary when no new one is due, so callers need no freshness logic of their own.
"""

import re
import json
import time
import hashlib
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from django.db import IntegrityError
from django.utils import timezone

import structlog
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema
from prometheus_client import Counter
from pydantic import ValidationError
from redis import Redis
from redis.exceptions import RedisError

from posthog.schema import DateRange, ErrorTrackingQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import build_openai_client, resolve_ai_gateway_config, team_distinct_id
from posthog.llm.semantic_enrichment import extract_json_object
from posthog.models import Team, User
from posthog.redis import get_client
from posthog.token_bucket import BucketDecision, BucketUnavailable, consume, peek, refund

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.contracts import UserNotOrganizationMemberError
from products.error_tracking.backend.facade.contracts import IssueSummaryCategory
from products.error_tracking.backend.facade.queries import run_error_tracking_query
from products.error_tracking.backend.facade.query_utils import (
    TREND_VOLUME_RESOLUTION,
    as_record,
    build_impact,
    build_trend,
    extract_release,
    first_event_window,
    parse_jsonish,
    to_number,
    truncate_text,
)
from products.error_tracking.backend.logic.issue_summary_config import (
    ISSUE_SUMMARY_BUDGET,
    ISSUE_SUMMARY_CATEGORY_MODEL,
    ISSUE_SUMMARY_FACTS_DATE_FROM,
    ISSUE_SUMMARY_FLAG,
    ISSUE_SUMMARY_HOLD_SECONDS,
    ISSUE_SUMMARY_LATEST_EVENT_LOOKBACK_DAYS,
    ISSUE_SUMMARY_LLM_TIMEOUT_SECONDS,
    ISSUE_SUMMARY_LOCK_TTL_SECONDS,
    ISSUE_SUMMARY_MAX_OUTPUT_TOKENS,
    ISSUE_SUMMARY_MIN_REGENERATE_INTERVAL,
    ISSUE_SUMMARY_MODEL,
    ISSUE_SUMMARY_PUBLISH_TIMEOUT_SECONDS,
    ISSUE_SUMMARY_QUEUED_TTL_SECONDS,
    ISSUE_SUMMARY_RECENT_EVENT_LOOKBACK_DAYS,
    ISSUE_SUMMARY_STACKTRACE_MAX_TOKENS,
)
from products.error_tracking.backend.logic.issue_summary_prompt import (
    ISSUE_SUMMARY_CATEGORY_QUESTION,
    ISSUE_SUMMARY_CATEGORY_QUESTION_ID,
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
from products.error_tracking.backend.tasks.tasks import generate_error_tracking_issue_summary
from products.error_tracking.backend.temporal.lifecycle.rendering import render_stacktrace
from products.ml_inference.backend.facade import api as ml_inference
from products.ml_inference.backend.facade.contracts import ChoiceAnswer, DecisionRequest

logger = structlog.get_logger(__name__)

ISSUE_SUMMARY_BUDGET_KEY_PREFIX = "error_tracking_issue_summary"
ISSUE_SUMMARY_LOCK_KEY_PREFIX = "error_tracking_issue_summary_lock"
ISSUE_SUMMARY_AI_PRODUCT = "error_tracking"
# The Go gateway keeps the prompt and the reply out of the AI observability project when this is set.
PRIVACY_MODE_HEADER = "X-PostHog-Privacy-Mode"

UNKNOWN = "unknown"
IN_APP_FRAME_MARKER = "[in-app]"
WAIT_POLL_INTERVAL_SECONDS = 0.25
# Event values must not open or close the <issue> block that fences them in the prompt.
ISSUE_FENCE_TAG = re.compile(r"</?\s*issue\s*>", re.IGNORECASE)
# A worker claims with this prefix and its own token, so only that worker can settle the claim.
LOCK_CLAIM_PREFIX = "claim:"
# Workers deployed before claim tokens claim with this value.
LEGACY_LOCK_CLAIM = "1"
LOCK_QUEUED = "queued"
# Takes the lock when the key is free or holds only the queued marker. Returns nil on success, else the value that holds it.
CLAIM_LUA = """
local held = redis.call('GET', KEYS[1])
if held == false or held == ARGV[1] then
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    return false
end
return held
"""
# Writes the outcome only while the key still holds the caller's claim. An empty TTL keeps the current one.
SETTLE_LUA = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return 0
end
if ARGV[3] == '' then
    redis.call('SET', KEYS[1], ARGV[2], 'KEEPTTL')
else
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
end
return 1
"""
# Deletes the key only while it holds the queued marker, so a worker's claim or a hold outcome survives.
RELEASE_QUEUED_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class IssueSummaryOutcome(StrEnum):
    GENERATED = "generated"
    # A stored summary is younger than the regenerate interval.
    FRESH = "fresh"
    # A stored summary is older than the interval, but its inputs did not change.
    UNCHANGED = "unchanged"
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


# Outcomes that hold the issue past the lock TTL, because each try runs the input queries before it finds them.
HOLD_OUTCOMES = frozenset({IssueSummaryOutcome.NO_EXCEPTION, IssueSummaryOutcome.RATE_LIMITED})
# Outcomes that leave a summary current. The claim then stays until the lock expires.
SETTLED_OUTCOMES = frozenset({IssueSummaryOutcome.GENERATED, IssueSummaryOutcome.UNCHANGED, IssueSummaryOutcome.FRESH})

ISSUE_SUMMARY_OUTCOMES = Counter(
    "error_tracking_issue_summary_total",
    "Issue summary requests by outcome",
    labelnames=("outcome",),
)


@frozen
class IssueSummaryResult:
    outcome: IssueSummaryOutcome
    # The new summary, or the stored one when no new one was generated.
    summary: ErrorTrackingIssueSummary | None


@frozen
class IssueSummaryInputs:
    prompt: str
    input_hash: str


def issue_summaries_enabled(team_id: int) -> bool:
    return team_flag_enabled(ISSUE_SUMMARY_FLAG, team_id)


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


def regeneration_due(summary: ErrorTrackingIssueSummary | None, now: datetime) -> bool:
    return summary is None or now - summary.checked_at >= ISSUE_SUMMARY_MIN_REGENERATE_INTERVAL


def generation_blocked(team_id: int, stored: ErrorTrackingIssueSummary | None) -> IssueSummaryOutcome | None:
    """The reason no generation can start now, or None when one can."""
    # Checked first because it needs no network call or query, and most reads find a fresh summary.
    if not regeneration_due(stored, timezone.now()):
        return IssueSummaryOutcome.FRESH
    if not issue_summaries_enabled(team_id):
        return IssueSummaryOutcome.DISABLED
    if not is_ai_data_processing_approved(team_id):
        return IssueSummaryOutcome.AI_NOT_APPROVED
    return None


def start_issue_summary_generation(team_id: int, issue_id: UUID | str) -> bool:
    """Queue generation in the background when a summary may be due. True when a summary may arrive soon.

    False means nothing will change soon, so the caller should not wait.
    """
    if generation_blocked(team_id, get_issue_summary(team_id, issue_id)) is not None:
        return False
    try:
        client = _start_client()
        key = _lock_key(team_id, issue_id)
        if client.set(key, LOCK_QUEUED, nx=True, ex=ISSUE_SUMMARY_QUEUED_TTL_SECONDS):
            return _queue_generation(team_id, issue_id)
        held = client.get(key)
    except RedisError:
        logger.warning("error_tracking_issue_summary_lock_unavailable", team_id=team_id, exc_info=True)
        return _queue_generation(team_id, issue_id)
    return _lock_outcome(held) == IssueSummaryOutcome.IN_PROGRESS


def _queue_generation(team_id: int, issue_id: UUID | str) -> bool:
    try:
        _publish_generation(team_id, issue_id)
    except Exception as error:
        capture_exception(error, {"team_id": team_id, "issue_id": str(issue_id)})
        # Without a task, the queued marker would keep reads waiting until it expires.
        try:
            _start_client().register_script(RELEASE_QUEUED_LUA)(keys=[_lock_key(team_id, issue_id)], args=[LOCK_QUEUED])
        except RedisError:
            logger.warning("error_tracking_issue_summary_lock_unavailable", team_id=team_id, exc_info=True)
        return False
    return True


def _start_client() -> Redis:
    """The lock client for the start, with the publish timeouts.

    The lock and the broker share a Redis, so the default client's longer socket timeout would hold the read first.
    """
    return get_client(
        socket_timeout=ISSUE_SUMMARY_PUBLISH_TIMEOUT_SECONDS,
        socket_connect_timeout=ISSUE_SUMMARY_PUBLISH_TIMEOUT_SECONDS,
    )


def _publish_generation(team_id: int, issue_id: UUID | str) -> None:
    """Queue the task on a connection with short timeouts and no publish retries.

    The shared producer pool has no socket timeout and retries the publish, so an unresponsive broker blocks the read.
    """
    timeout = ISSUE_SUMMARY_PUBLISH_TIMEOUT_SECONDS
    with generate_error_tracking_issue_summary.app.connection_for_write(
        connect_timeout=timeout,
        transport_options={"socket_timeout": timeout, "socket_connect_timeout": timeout},
    ) as connection:
        generate_error_tracking_issue_summary.apply_async(
            args=(team_id, str(issue_id)), connection=connection, retry=False
        )


def wait_for_issue_summary(
    team_id: int, issue_id: UUID | str, *, checked_after: datetime | None, timeout_seconds: float
) -> ErrorTrackingIssueSummary | None:
    """Poll for a summary generated or confirmed unchanged after `checked_after`, or any summary when it is None.

    Pass the time taken just before `start_issue_summary_generation`. Returns None at the timeout.
    The background task keeps running.
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        summary = get_issue_summary(team_id, issue_id)
        if summary is not None and (checked_after is None or summary.checked_at > checked_after):
            return summary
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(WAIT_POLL_INTERVAL_SECONDS, remaining))


def get_or_generate_issue_summary(team_id: int, issue_id: UUID | str) -> IssueSummaryResult:
    """Return a stored summary, or generate one when none is stored or a stale one is due.

    Generation runs at most once at a time per issue. A failure keeps the stored summary.
    """
    try:
        result = _get_or_generate(team_id, issue_id)
    except Exception:
        ISSUE_SUMMARY_OUTCOMES.labels(outcome=IssueSummaryOutcome.UNEXPECTED_ERROR.value).inc()
        raise
    ISSUE_SUMMARY_OUTCOMES.labels(outcome=result.outcome.value).inc()
    logger.info(
        "error_tracking_issue_summary",
        team_id=team_id,
        issue_id=str(issue_id),
        outcome=result.outcome.value,
        has_summary=result.summary is not None,
    )
    return result


def _get_or_generate(team_id: int, issue_id: UUID | str) -> IssueSummaryResult:
    stored = get_issue_summary(team_id, issue_id)
    if (blocked := generation_blocked(team_id, stored)) is not None:
        return IssueSummaryResult(outcome=blocked, summary=stored)
    claim = f"{LOCK_CLAIM_PREFIX}{uuid4().hex}"
    if (held := _claim_generation(team_id, issue_id, claim)) is not None:
        return IssueSummaryResult(outcome=held, summary=stored)

    try:
        result = _generate_claimed(team_id, issue_id)
    except Exception:
        _settle_claim(team_id, issue_id, claim, IssueSummaryOutcome.UNEXPECTED_ERROR)
        raise
    _settle_claim(team_id, issue_id, claim, result.outcome)
    return result


def _generate_claimed(team_id: int, issue_id: UUID | str) -> IssueSummaryResult:
    # Another worker can finish between the first read and the claim.
    stored = get_issue_summary(team_id, issue_id)
    if not regeneration_due(stored, timezone.now()):
        return IssueSummaryResult(outcome=IssueSummaryOutcome.FRESH, summary=stored)

    budget_key = f"{ISSUE_SUMMARY_BUDGET_KEY_PREFIX}:{team_id}"
    # The input queries run before `consume`, so an unchanged issue spends no token. This read keeps a team
    # with no tokens left from running them for every issue it opens. `consume` still makes the decision.
    if _budget_exhausted(budget_key):
        return IssueSummaryResult(outcome=IssueSummaryOutcome.RATE_LIMITED, summary=stored)

    team = Team.objects.get(id=team_id)
    try:
        inputs = build_issue_summary_inputs(team, issue_id)
    except Exception as error:
        capture_exception(error, {"team_id": team_id, "issue_id": str(issue_id)})
        logger.warning("error_tracking_issue_summary_inputs_failed", team_id=team_id, issue_id=str(issue_id))
        return IssueSummaryResult(outcome=IssueSummaryOutcome.INPUTS_ERROR, summary=stored)
    if isinstance(inputs, IssueSummaryOutcome):
        return IssueSummaryResult(outcome=inputs, summary=stored)
    if stored is not None and stored.input_hash == inputs.input_hash:
        stored.checked_at = timezone.now()
        ErrorTrackingIssueSummary.objects.for_team(team_id).filter(id=stored.id).update(checked_at=stored.checked_at)
        return IssueSummaryResult(outcome=IssueSummaryOutcome.UNCHANGED, summary=stored)

    decision = consume(budget_key, ISSUE_SUMMARY_BUDGET)
    match decision:
        case BucketDecision(allowed=False):
            return IssueSummaryResult(outcome=IssueSummaryOutcome.RATE_LIMITED, summary=stored)
        case BucketUnavailable(error=bucket_error):
            # Fail open: the per-issue lock and the regenerate interval still bound the spend.
            logger.warning("error_tracking_issue_summary_budget_unavailable", team_id=team_id, error=bucket_error)

    # Only the Go gateway honours privacy mode, so the Python gateway fallback is never used.
    if resolve_ai_gateway_config() is None:
        refund(budget_key, ISSUE_SUMMARY_BUDGET)
        return IssueSummaryResult(outcome=IssueSummaryOutcome.GATEWAY_UNCONFIGURED, summary=stored)

    try:
        raw = _call_model(team_id, inputs.prompt)
    except Exception as error:
        capture_exception(error, {"team_id": team_id, "issue_id": str(issue_id)})
        logger.warning("error_tracking_issue_summary_model_failed", team_id=team_id, issue_id=str(issue_id))
        return IssueSummaryResult(outcome=IssueSummaryOutcome.MODEL_ERROR, summary=stored)

    response = parse_summary_response(raw)
    if response is None:
        logger.warning("error_tracking_issue_summary_invalid_output", team_id=team_id, issue_id=str(issue_id))
        return IssueSummaryResult(outcome=IssueSummaryOutcome.INVALID_OUTPUT, summary=stored)

    category = infer_issue_category(team_id, inputs.prompt)
    generated_at = timezone.now()
    try:
        summary, _ = ErrorTrackingIssueSummary.objects.for_team(team_id).update_or_create(
            issue_id=issue_id,
            defaults={
                "team_id": team_id,
                "content": {**response.model_dump(), "category": category.value if category else None},
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


def _budget_exhausted(budget_key: str) -> bool:
    decision = peek(budget_key, ISSUE_SUMMARY_BUDGET)
    return isinstance(decision, BucketDecision) and not decision.allowed


def _lock_key(team_id: int, issue_id: UUID | str) -> str:
    return f"{ISSUE_SUMMARY_LOCK_KEY_PREFIX}:{team_id}:{issue_id}"


def _claim_generation(team_id: int, issue_id: UUID | str, claim: str) -> IssueSummaryOutcome | None:
    """None when this worker now holds the issue under `claim`, else the outcome that holds it."""
    try:
        held = get_client().register_script(CLAIM_LUA)(
            keys=[_lock_key(team_id, issue_id)],
            args=[LOCK_QUEUED, claim, ISSUE_SUMMARY_LOCK_TTL_SECONDS],
        )
    except RedisError:
        # Fail open, as the budget does: a Redis outage can let two concurrent reads both pay.
        logger.warning("error_tracking_issue_summary_lock_unavailable", team_id=team_id, exc_info=True)
        return None
    return _lock_outcome(held) if held is not None else None


def _lock_outcome(held: bytes | str | None) -> IssueSummaryOutcome:
    """A live claim or a queued task means a summary may come. Every other value is the outcome that stopped generation."""
    value = held.decode() if isinstance(held, bytes) else held
    if value is None or value in (LEGACY_LOCK_CLAIM, LOCK_QUEUED) or value.startswith(LOCK_CLAIM_PREFIX):
        return IssueSummaryOutcome.IN_PROGRESS
    return IssueSummaryOutcome(value)


def _settle_claim(team_id: int, issue_id: UUID | str, claim: str, outcome: IssueSummaryOutcome) -> None:
    """Replace this worker's claim with `outcome` when no summary came of it, so reads stop waiting for one.

    A hold outcome extends the lock. Any other failure keeps the lock TTL, so the retry spacing does not change.
    Nothing is written when the key no longer holds `claim`: the lock expired, or another read took the issue.
    """
    if outcome in SETTLED_OUTCOMES:
        return
    ttl = str(ISSUE_SUMMARY_HOLD_SECONDS) if outcome in HOLD_OUTCOMES else ""
    try:
        get_client().register_script(SETTLE_LUA)(keys=[_lock_key(team_id, issue_id)], args=[claim, outcome.value, ttl])
    except RedisError:
        logger.warning("error_tracking_issue_summary_hold_unavailable", team_id=team_id, exc_info=True)


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
# `_exception_event_properties` drops every other key, so a property left out is missing from the prompt, not leaked.
ISSUE_SUMMARY_SOURCE_PROPERTIES = frozenset(
    {"$exception_list", "$exception_level", "$lib", "$current_url", "$exception_release"}
)


def build_issue_summary_inputs(team: Team, issue_id: UUID | str) -> IssueSummaryInputs | IssueSummaryOutcome:
    """Build the prompt and the input hash, or say why the issue cannot be summarised."""
    issue = ErrorTrackingIssue.objects.with_first_seen().filter(team_id=team.id, id=issue_id).first()
    if issue is None:
        return IssueSummaryOutcome.ISSUE_MISSING
    first_seen: datetime | None = getattr(issue, "first_seen", None)

    now = timezone.now()
    event_properties: dict[str, object] = {}
    for lookback_days in (ISSUE_SUMMARY_RECENT_EVENT_LOOKBACK_DAYS, ISSUE_SUMMARY_LATEST_EVENT_LOOKBACK_DAYS):
        event_properties = _exception_event_properties(
            team, issue_id, after=now - timedelta(days=lookback_days), before=now, latest=True
        )
        if event_properties:
            break
    stack_trace = (
        render_stacktrace(mark_in_app_frames(event_properties), ISSUE_SUMMARY_STACKTRACE_MAX_TOKENS)
        if event_properties
        else ""
    )
    if not stack_trace:
        return IssueSummaryOutcome.NO_EXCEPTION

    first_event_properties: dict[str, object] = {}
    if (window := first_event_window(first_seen)) is not None:
        first_event_properties = _exception_event_properties(
            team,
            issue_id,
            after=datetime.fromisoformat(window.after),
            before=datetime.fromisoformat(window.before),
            latest=False,
        )

    aggregated_issue = _aggregated_issue(team, issue_id)
    impact = build_impact(aggregated_issue)
    trend = build_trend(aggregated_issue, first_seen) or {}
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
        "occurrences": _count(impact.get("occurrences")),
        "users": _count(impact.get("users")),
        "sessions": _count(impact.get("sessions")),
    }
    prompt = ISSUE_SUMMARY_INPUT_TEMPLATE.format(
        **{name: ISSUE_FENCE_TAG.sub("", value) for name, value in fields.items()}
    )
    fingerprints = list(
        ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team.id, issue_id=issue_id).values_list(
            "fingerprint", flat=True
        )
    )
    occurrences = to_number(impact.get("occurrences"))
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


def _exception_event_properties(
    team: Team, issue_id: UUID | str, *, after: datetime, before: datetime, latest: bool
) -> dict[str, object]:
    query = parse_select(
        f"""
        SELECT properties
        FROM events
        WHERE event = '$exception'
          AND issue_id = {{issue_id}}
          AND timestamp >= {{after}}
          AND timestamp < {{before}}
        ORDER BY timestamp {"DESC" if latest else "ASC"}
        LIMIT 1
        """,
        placeholders={
            "issue_id": ast.Constant(value=str(issue_id)),
            "after": ast.Constant(value=after),
            "before": ast.Constant(value=before),
        },
    )
    with tags_context(product=Product.ERROR_TRACKING, feature=Feature.QUERY):
        response = execute_hogql_query(
            query=query,
            team=team,
            query_type="ErrorTrackingIssueSummaryEventProperties",
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.ERROR_TRACKING,
        )
    if not response.results:
        return {}
    properties = as_record(parse_jsonish(response.results[0][0])) or {}
    return {key: value for key, value in properties.items() if key in ISSUE_SUMMARY_SOURCE_PROPERTIES}


def _aggregated_issue(team: Team, issue_id: UUID | str) -> dict[str, object]:
    query = ErrorTrackingQuery(
        kind="ErrorTrackingQuery",
        issueId=str(issue_id),
        dateRange=DateRange(date_from=ISSUE_SUMMARY_FACTS_DATE_FROM),
        filterTestAccounts=True,
        volumeResolution=TREND_VOLUME_RESOLUTION,
        limit=1,
        orderBy="last_seen",
        orderDirection="DESC",
        withAggregations=True,
        withFirstEvent=False,
        withLastEvent=False,
        tags={"productKey": "error_tracking"},
    )
    data = run_error_tracking_query(team, query)
    results = data.get("results")
    return (as_record(results[0]) or {}) if isinstance(results, list) and results else {}


ISSUE_SUMMARY_RESPONSE_FORMAT: ResponseFormatJSONSchema = {
    "type": "json_schema",
    "json_schema": {
        "name": "issue_summary",
        "strict": True,
        "schema": IssueSummaryResponse.model_json_schema(),
    },
}


def _call_model(team_id: int, prompt: str) -> str:
    client: OpenAI = build_openai_client(
        "django",
        ai_product=ISSUE_SUMMARY_AI_PRODUCT,
        properties={"team_id": str(team_id)},
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


def infer_issue_category(team_id: int, prompt: str) -> IssueSummaryCategory | None:
    """Ask the decision model for a category. Any failure leaves the category empty."""
    try:
        result = ml_inference.decide_when_available(
            DecisionRequest(
                team_id=team_id,
                state=prompt,
                questions={ISSUE_SUMMARY_CATEGORY_QUESTION_ID: ISSUE_SUMMARY_CATEGORY_QUESTION},
                model=ISSUE_SUMMARY_CATEGORY_MODEL,
                privacy_mode=True,
            )
        )
    except Exception:
        logger.warning("error_tracking_issue_summary_category_failed", team_id=team_id, exc_info=True)
        return None
    answer = result.answers.get(ISSUE_SUMMARY_CATEGORY_QUESTION_ID)
    if not isinstance(answer, ChoiceAnswer) or answer.choice not in IssueSummaryCategory.values:
        logger.warning("error_tracking_issue_summary_category_unexpected", team_id=team_id, answer=repr(answer))
        return None
    return IssueSummaryCategory(answer.choice)
