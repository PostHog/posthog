"""Serve one person's ranked inbox list to the `for_me` endpoint: reuse a stored list, or build a new one.

A stored list is reused while it is younger than `freshness_minutes` and its input hash matches the current
inputs. A request with `focus` always builds. The focus is part of the hash, so an unfocused request never
reuses a focused list. Builds spend two per-person token buckets. A throttled request gets the latest stored
list, or `BuildThrottledError` when there is none.
"""

import datetime
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume, refund

from products.signals.backend.activity_summary.read import ActivitySummaryStatus, get_summary
from products.signals.backend.models import PersonalInboxRanking
from products.signals.backend.personal_ranking.candidates import Candidate, gather_candidates
from products.signals.backend.personal_ranking.config import PersonalRankingConfig, read_config
from products.signals.backend.personal_ranking.logic import build_personal_ranking, input_hash, normalize_focus
from products.signals.backend.ranking.report_predictions import ReportPredictions

logger = structlog.get_logger(__name__)

ServeStatus = Literal["ready", "unavailable"]

_BUCKET_PREFIX = "personal_ranking_build_rate"


class BuildThrottledError(Exception):
    def __init__(self, retry_after: int | None) -> None:
        super().__init__("Personal inbox ranking build throttled.")
        self.retry_after = retry_after


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
class ServedRanking:
    status: ServeStatus
    personalized: bool
    # True when the list comes from storage, False when this request built it.
    cached: bool
    # True when the list does not reflect the current inputs, because a build was throttled.
    stale: bool
    fallback_reason: str | None
    generated_at: datetime.datetime | None
    latency_ms: int | None
    activity_summary_version: int | None
    candidates_considered: int
    ranked_count: int
    results: tuple[ServedEntry, ...]
    folded: tuple[ServedFold, ...]


UNAVAILABLE = ServedRanking(
    status="unavailable",
    personalized=False,
    cached=False,
    stale=False,
    fallback_reason=None,
    generated_at=None,
    latency_ms=None,
    activity_summary_version=None,
    candidates_considered=0,
    ranked_count=0,
    results=(),
    folded=(),
)


def _spend_build(team_id: int, user_id: int, config: PersonalRankingConfig) -> int | None:
    """Spend one build from both buckets. Returns None when allowed, else the seconds until the next build."""
    hourly = Budget(burst=config.build_burst, per_hour=config.builds_per_hour)
    # Refills the daily cap over 24 hours, so a person cannot spend it twice in one day.
    daily = Budget(burst=config.builds_per_day, per_hour=max(1, -(-config.builds_per_day // 24)))
    hourly_key = f"{_BUCKET_PREFIX}:hour:{team_id}:{user_id}"
    hourly_decision = consume(hourly_key, hourly)
    if isinstance(hourly_decision, BucketDecision) and not hourly_decision.allowed:
        return hourly_decision.retry_after
    daily_decision = consume(f"{_BUCKET_PREFIX}:day:{team_id}:{user_id}", daily)
    if isinstance(daily_decision, BucketDecision) and not daily_decision.allowed:
        if isinstance(hourly_decision, BucketDecision):
            refund(hourly_key, hourly)
        return daily_decision.retry_after
    if isinstance(hourly_decision, BucketUnavailable) or isinstance(daily_decision, BucketUnavailable):
        # Fail open, so an unreachable Redis does not hide the list.
        logger.warning("signals.personal_ranking.build_bucket_unavailable", team_id=team_id, user_id=user_id)
    return None


def _ready_summary_version(team: Team, user: User) -> int | None:
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
    row: PersonalInboxRanking, candidates: Sequence[Candidate], *, limit: int, cached: bool, stale: bool
) -> ServedRanking:
    result = row.result or {}
    ranked = result.get("ranked") or []
    by_id = {candidate.report_id: candidate for candidate in candidates}
    return ServedRanking(
        status="ready",
        personalized=row.personalized,
        cached=cached,
        stale=stale,
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


def serve_personal_ranking(
    team: Team,
    user: User,
    *,
    limit: int | None = None,
    refresh: bool = False,
    focus: str | None = None,
    config: PersonalRankingConfig | None = None,
) -> ServedRanking:
    config = config or read_config()
    if not config.enabled:
        return UNAVAILABLE
    limit = min(max(limit or config.default_limit, 1), config.max_limit)
    focus = normalize_focus(focus, config.focus_max_chars)
    now = timezone.now()

    latest = (
        PersonalInboxRanking.objects.for_team(team.id).filter(user_id=user.id).order_by("-created_at", "-id").first()
    )
    candidates = gather_candidates(team, user, config, now=now, with_sources=False)
    current_hash = input_hash(candidates, activity_summary_version=_ready_summary_version(team, user), focus=focus)
    current = (
        latest is not None
        and latest.created_at >= now - datetime.timedelta(minutes=config.freshness_minutes)
        and latest.input_hash == current_hash
    )
    if latest is not None and current and not refresh and focus is None:
        return _serve_row(latest, candidates, limit=limit, cached=True, stale=False)

    retry_after = _spend_build(team.id, user.id, config)
    if retry_after is not None:
        if latest is None:
            raise BuildThrottledError(retry_after)
        return _serve_row(latest, candidates, limit=limit, cached=True, stale=not current)

    build = build_personal_ranking(team, user, focus=focus, limit=limit, config=config)
    if build.ranking_id is None:
        return UNAVAILABLE
    row = PersonalInboxRanking.objects.for_team(team.id).get(id=build.ranking_id, team_id=team.id, user_id=user.id)
    return _serve_row(row, build.candidates, limit=limit, cached=False, stale=False)
