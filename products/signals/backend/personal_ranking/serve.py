"""Serve one person's ranked inbox list to the `for_me` endpoint. A request never waits on the model.

A stored list is reused while it was built or checked by the tick less than `freshness_minutes` ago and its input
hash matches the current inputs. Otherwise, and for every `refresh` or `focus` request, the read queues one
background build per person and serves the latest stored list as stale, or the candidates in inbox order when
there is none. The focus is part of the hash, so an unfocused request never reuses a focused list. A build that
stores a list for the current inputs while the read runs answers the read, also a `refresh` read, so the read
queues no second build. A lock lets one build per person run at a time, and each queued build spends two
per-person token buckets. A build that may call the model also spends the shared daily limit of the region
(`build_budget.py`). `wait_seconds` waits a bounded time for the queued build to store its list, counted from the
start of the request.

While the stored list is young enough, the read checks only the reports that list considered, with a fixed number
of queries, and skips the candidate pool queries. A new report joins at the next build after the list ages out.
"""

import time
import datetime
import dataclasses
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any, Literal

from django.core.cache import cache
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume, refund

from products.signals.backend.activity_summary.read import ActivitySummaryStatus, get_summary
from products.signals.backend.models import PersonalInboxRanking
from products.signals.backend.personal_ranking.build_budget import DAILY_BUILD_COST, spend_shared_build
from products.signals.backend.personal_ranking.candidates import Candidate, gather_candidates, stored_candidates
from products.signals.backend.personal_ranking.config import PersonalRankingConfig, read_config
from products.signals.backend.personal_ranking.logic import (
    input_hash,
    may_call_model,
    model_order_reason,
    normalize_focus,
)
from products.signals.backend.personal_ranking.validation import model_order
from products.signals.backend.personal_ranking_tasks import (
    BUILD_LOCK_TTL_SECONDS,
    build_lock_key,
    build_personal_inbox_ranking,
)
from products.signals.backend.ranking.report_predictions import ReportPredictions

logger = structlog.get_logger(__name__)

ServeStatus = Literal["ready", "unavailable"]

_BUCKET_PREFIX = "personal_ranking_build_rate"
MAX_WAIT_SECONDS = 30
_WAIT_POLL_SECONDS = 0.5

# Why a list with no stored build is in inbox order.
FALLBACK_BUILDING = "building"
FALLBACK_RATE_LIMITED = "rate_limited"
FALLBACK_BUILD_FAILED = "build_failed"

BuildStart = Literal["started", "running", "rate_limited", "failed"]


@frozen
class ServedReport:
    id: str
    title: str
    status: str
    priority: str | None
    pull_request_state: str | None
    # None when the person cannot see the ranking model's output.
    predictions: ReportPredictions | None


@frozen
class ServedEntry:
    rank: int
    tier: str
    reason: str
    next_step: str | None
    matched_theme: str | None
    needs_you: tuple[str, ...]
    ranked_by: str
    report: ServedReport


@frozen
class ServedFold:
    report_id: str
    into_report_id: str
    reason: str


@frozen
class ReadTimings:
    """The milliseconds each phase of a read took. None when the read skipped the phase."""

    # The latest stored row, the activity summary, and the facts of the reports the stored list considered.
    check_ms: int | None = None
    # The candidate pools and the facts of every candidate.
    gather_ms: int | None = None
    # The poll for a new row, when `wait_seconds` asked for it.
    wait_ms: int | None = None


@frozen
class ServedRanking:
    status: ServeStatus
    personalized: bool
    # True when the list comes from storage, False when it is the inbox-order fallback or a build this request waited on.
    cached: bool
    # True when the list does not reflect the current inputs.
    stale: bool
    # True when a build for the person is queued or running.
    building: bool
    fallback_reason: str | None
    generated_at: datetime.datetime | None
    latency_ms: int | None
    activity_summary_version: int | None
    candidates_considered: int
    ranked_count: int
    results: tuple[ServedEntry, ...]
    folded: tuple[ServedFold, ...]
    timings: ReadTimings = ReadTimings()


UNAVAILABLE = ServedRanking(
    status="unavailable",
    personalized=False,
    cached=False,
    stale=False,
    building=False,
    fallback_reason=None,
    generated_at=None,
    latency_ms=None,
    activity_summary_version=None,
    candidates_considered=0,
    ranked_count=0,
    results=(),
    folded=(),
)


def _spend_build(team_id: int, user_id: int, config: PersonalRankingConfig, *, calls_model: bool) -> int | None:
    """Spend one build from the per-person buckets, and from the shared limit when the build may call the model.

    Returns None when allowed, else the seconds until the next build.
    """
    hourly = Budget(burst=config.build_burst, per_hour=config.builds_per_hour)
    # A build costs one token per hour of the day, and the bucket refills `builds_per_day` tokens an hour,
    # so it refills exactly `builds_per_day` builds a day. A whole-token rate per build would round it up.
    daily = Budget(burst=config.builds_per_day * DAILY_BUILD_COST, per_hour=config.builds_per_day)
    hourly_key = f"{_BUCKET_PREFIX}:hour:{team_id}:{user_id}"
    daily_key = f"{_BUCKET_PREFIX}:day:{team_id}:{user_id}"
    hourly_decision = consume(hourly_key, hourly)
    if isinstance(hourly_decision, BucketDecision) and not hourly_decision.allowed:
        return hourly_decision.retry_after
    daily_decision = consume(daily_key, daily, cost=DAILY_BUILD_COST)
    if isinstance(daily_decision, BucketDecision) and not daily_decision.allowed:
        if isinstance(hourly_decision, BucketDecision):
            refund(hourly_key, hourly)
        return daily_decision.retry_after
    if isinstance(hourly_decision, BucketUnavailable) or isinstance(daily_decision, BucketUnavailable):
        # Fail open, so an unreachable Redis does not hide the list.
        logger.warning("signals.personal_ranking.build_bucket_unavailable", team_id=team_id, user_id=user_id)
    if calls_model and (retry_after := spend_shared_build(config)) is not None:
        if isinstance(hourly_decision, BucketDecision):
            refund(hourly_key, hourly)
        if isinstance(daily_decision, BucketDecision):
            refund(daily_key, daily, cost=DAILY_BUILD_COST)
        return retry_after
    return None


def _start_build(
    team: Team,
    user: User,
    config: PersonalRankingConfig,
    focus: str | None,
    limit: int,
    *,
    calls_model: bool,
    seen: PersonalInboxRanking | None,
    current_hash: str,
) -> BuildStart | PersonalInboxRanking:
    """Queue one background build, unless one is already running for the person or the buckets refuse it.

    Returns a row instead when an unfocused request finds a row for the current inputs stored after `seen`.
    """
    lock_key = build_lock_key(team.id, user.id)
    locked = False
    try:
        locked = cache.add(lock_key, "1", timeout=BUILD_LOCK_TTL_SECONDS)
        if not locked:
            return "running"
        # A build can store its row and free the lock after the read looked for a row.
        if focus is None and (stored := _row_stored_since(team, user, seen, current_hash)) is not None:
            cache.delete(lock_key)
            return stored
        if _spend_build(team.id, user.id, config, calls_model=calls_model) is not None:
            cache.delete(lock_key)
            return "rate_limited"
        build_personal_inbox_ranking.delay(team.id, user.id, focus, limit)
        return "started"
    except Exception as error:
        # A broker or cache failure must not fail the read, which still has a list to serve.
        capture_exception(error, {"team_id": team.id, "user_id": user.id})
        if locked:
            with suppress(Exception):
                cache.delete(lock_key)
        return "failed"


def latest_row(team: Team, user: User) -> PersonalInboxRanking | None:
    return PersonalInboxRanking.objects.for_team(team.id).filter(user_id=user.id).order_by("-created_at", "-id").first()


def _row_stored_since(
    team: Team, user: User, seen: PersonalInboxRanking | None, current_hash: str
) -> PersonalInboxRanking | None:
    row = latest_row(team, user)
    if row is None or (seen is not None and row.id == seen.id) or row.input_hash != current_hash:
        return None
    return row


def _wait_for_new_row(
    team: Team, user: User, previous: PersonalInboxRanking | None, deadline: float
) -> PersonalInboxRanking | None:
    while True:
        row = latest_row(team, user)
        if row is not None and (previous is None or row.id != previous.id):
            return row
        if time.monotonic() >= deadline:
            return None
        time.sleep(_WAIT_POLL_SECONDS)


def _elapsed_ms(since: float) -> int:
    return round((time.monotonic() - since) * 1000)


def ready_summary_version(team: Team, user: User) -> int | None:
    summary = get_summary(team, user.id)
    return summary.version if summary is not None and summary.status == ActivitySummaryStatus.READY else None


def _served_report(candidate: Candidate) -> ServedReport:
    return ServedReport(
        id=candidate.report_id,
        title=candidate.title,
        status=candidate.status,
        priority=candidate.priority,
        pull_request_state=candidate.pull_request_state,
        predictions=candidate.predictions,
    )


def _entries(ranked: Sequence[Mapping[str, Any]], by_id: Mapping[str, Candidate], limit: int) -> list[ServedEntry]:
    entries: list[ServedEntry] = []
    for row in ranked:
        candidate = by_id.get(row["report_id"])
        # A report that left the candidates since the build, for example a resolved one, drops out.
        if candidate is None:
            continue
        theme = (row.get("matched") or {}).get("theme")
        entries.append(
            ServedEntry(
                rank=row["rank"],
                tier=row["tier"],
                reason=row["reason"],
                next_step=row.get("next_step"),
                matched_theme=theme,
                # The current facts, not the model's echo of them, and also set on entries the model did not rank.
                needs_you=candidate.needs_you,
                ranked_by=row["ranked_by"],
                report=_served_report(candidate),
            )
        )
        if len(entries) == limit:
            break
    return entries


def _serve_row(
    row: PersonalInboxRanking,
    candidates: Sequence[Candidate],
    *,
    limit: int,
    cached: bool,
    stale: bool,
    building: bool,
) -> ServedRanking:
    result = row.result or {}
    ranked = result.get("ranked") or []
    by_id = {candidate.report_id: candidate for candidate in candidates}
    return ServedRanking(
        status="ready",
        personalized=row.personalized,
        cached=cached,
        stale=stale,
        building=building,
        fallback_reason=row.fallback_reason,
        generated_at=row.created_at,
        latency_ms=row.latency_ms,
        activity_summary_version=row.activity_summary_version,
        candidates_considered=len(row.candidate_ids or ()),
        ranked_count=len(ranked),
        results=tuple(_entries(ranked, by_id, limit)),
        folded=tuple(
            ServedFold(report_id=fold["report_id"], into_report_id=fold["into_report_id"], reason=fold["reason"])
            for fold in result.get("folded") or ()
        ),
    )


def _serve_inbox_order(candidates: Sequence[Candidate], *, limit: int, building: bool, reason: str) -> ServedRanking:
    """The list before any build is stored: every candidate in inbox order, with no model call."""
    by_ref = {candidate.ref: candidate for candidate in candidates}
    ranked = model_order(
        [candidate.ref for candidate in candidates],
        {candidate.ref: model_order_reason(candidate) for candidate in candidates},
        limit,
    )
    return ServedRanking(
        status="ready",
        personalized=False,
        cached=False,
        stale=False,
        building=building,
        fallback_reason=reason,
        generated_at=None,
        latency_ms=None,
        activity_summary_version=None,
        candidates_considered=len(candidates),
        ranked_count=len(ranked),
        results=tuple(
            ServedEntry(
                rank=entry.rank,
                tier=entry.tier,
                reason=entry.reason,
                next_step=None,
                matched_theme=None,
                needs_you=by_ref[entry.ref].needs_you,
                ranked_by=entry.ranked_by,
                report=_served_report(by_ref[entry.ref]),
            )
            for entry in ranked[:limit]
        ),
        folded=(),
    )


def serve_personal_ranking(
    team: Team,
    user: User,
    *,
    limit: int | None = None,
    refresh: bool = False,
    focus: str | None = None,
    wait_seconds: int = 0,
    config: PersonalRankingConfig | None = None,
) -> ServedRanking:
    config = config or read_config()
    if not config.enabled:
        return UNAVAILABLE
    limit = min(max(limit or config.default_limit, 1), config.max_limit)
    focus = normalize_focus(focus, config.focus_max_chars)
    wait_seconds = min(max(wait_seconds, 0), MAX_WAIT_SECONDS)
    started = time.monotonic()
    gather_ms: int | None = None
    wait_ms: int | None = None

    def timed(served: ServedRanking) -> ServedRanking:
        return dataclasses.replace(served, timings=ReadTimings(check_ms=check_ms, gather_ms=gather_ms, wait_ms=wait_ms))

    def fresh(row: PersonalInboxRanking | None) -> bool:
        return row is not None and (row.checked_at or row.created_at) >= now - datetime.timedelta(
            minutes=config.freshness_minutes
        )

    now = timezone.now()
    started_with = latest_row(team, user)
    summary_version = ready_summary_version(team, user)
    if started_with is not None and fresh(started_with) and not refresh and focus is None:
        stored = stored_candidates(team, user, started_with.candidate_ids or ())
        if input_hash(stored, activity_summary_version=summary_version, focus=None) == started_with.input_hash:
            check_ms = _elapsed_ms(started)
            return timed(_serve_row(started_with, stored, limit=limit, cached=True, stale=False, building=False))
    check_ms = _elapsed_ms(started)

    gather_started = time.monotonic()
    candidates = gather_candidates(team, user, config, now=now, with_sources=False)
    current_hash = input_hash(candidates, activity_summary_version=summary_version, focus=focus)
    # Read again, because a build can store a row while the candidates are gathered.
    latest = latest_row(team, user)
    current = latest is not None and fresh(latest) and latest.input_hash == current_hash
    gather_ms = _elapsed_ms(gather_started)
    # A row stored after this read started also answers a refresh.
    stored_since_start = latest is not None and (started_with is None or latest.id != started_with.id)
    if latest is not None and current and focus is None and (not refresh or stored_since_start):
        return timed(_serve_row(latest, candidates, limit=limit, cached=True, stale=False, building=False))

    calls_model = bool(candidates) and may_call_model(team, summary_ready=summary_version is not None)
    start = _start_build(
        team, user, config, focus, limit, calls_model=calls_model, seen=latest, current_hash=current_hash
    )
    if isinstance(start, PersonalInboxRanking):
        return timed(_serve_row(start, candidates, limit=limit, cached=True, stale=False, building=False))
    building = start in ("started", "running")
    if building and wait_seconds:
        wait_started = time.monotonic()
        built = _wait_for_new_row(team, user, latest, started + wait_seconds)
        wait_ms = _elapsed_ms(wait_started)
        if built is not None:
            stale = built.input_hash != current_hash
            return timed(_serve_row(built, candidates, limit=limit, cached=False, stale=stale, building=False))
    if latest is not None:
        return timed(_serve_row(latest, candidates, limit=limit, cached=True, stale=not current, building=building))
    reason = (
        FALLBACK_BUILDING if building else FALLBACK_RATE_LIMITED if start == "rate_limited" else FALLBACK_BUILD_FAILED
    )
    return timed(_serve_inbox_order(candidates, limit=limit, building=building, reason=reason))
