"""The reports a personal ranking considers: a few server-side pools, deduped and capped, with the facts the prompt shows.

The pools come in the configured order, and a report keeps the position of the first pool that holds it.
That order is the model order: the fallback when the LLM does not rank a report.
"""

import datetime
from collections.abc import Sequence
from typing import Literal

from django.db.models import Max, QuerySet

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.artefact_schemas import ActionabilityChoice
from products.signals.backend.briefing_reports import (
    SUMMARY_LEAD_LIMIT,
    implementation_pull_request_state,
    report_ids_naming_user,
    reports_for_person,
    summary_lead,
)
from products.signals.backend.implementation_pr import (
    fetch_implementation_pr_state_for_reports,
    implementation_pr_report_filter,
)
from products.signals.backend.models import AutonomyPriority, SignalReport, SignalReportArtefact
from products.signals.backend.personal_ranking.config import CandidatePool, PersonalRankingConfig, candidate_pools
from products.signals.backend.ranking.access import can_view_inbox_ranking
from products.signals.backend.ranking.inbox_sort import InboxRanker, latest_ranking_value, resolve_recommended_ranker
from products.signals.backend.ranking.report_predictions import ReportPredictions, read_report_predictions
from products.signals.backend.ranking.staleness import EDIT_ARTEFACT_TYPES
from products.signals.backend.report_claims import reports_claimed_for_user
from products.signals.backend.report_lifecycle import report_status_filter
from products.signals.backend.report_priority import latest_priority_rank, latest_report_priorities
from products.signals.backend.signal_metadata import fetch_source_products_for_reports

logger = structlog.get_logger(__name__)

NeedsYouKind = Literal["suggested_reviewer", "claimed", "waiting_on_input"]

EXCLUDED_STATUSES: tuple[str, ...] = (
    SignalReport.Status.RESOLVED,
    SignalReport.Status.SUPPRESSED,
    SignalReport.Status.FAILED,
    SignalReport.Status.CLOSED,
    SignalReport.Status.DELETED,
)
_OPEN_STATUSES = (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)
# The recommended order is computed here, so the `for_you` pool reads at most this many reports to sort.
_FOR_YOU_SCAN_LIMIT = 300
_TITLE_MAX_CHARS = 200
_DECILES = 10


@frozen
class Candidate:
    # `c1` to `cN`, the label the prompt uses in place of the report id.
    ref: str
    report_id: str
    title: str
    summary_lead: str
    status: str
    priority: str | None
    # One of `IMPLEMENTATION_PR_STATES`, or None when the report has no implementation PR.
    pull_request_state: str | None
    source_products: tuple[str, ...]
    scout_name: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    # None when the person cannot see the ranking model's output.
    predictions: ReportPredictions | None
    needs_you: tuple[NeedsYouKind, ...]
    tags: tuple[str, ...]
    # The names of the configured pools that hold the report, in pool order.
    pools: tuple[str, ...]


# Compares field by field in declaration order, so the order of the fields is the sort order.
@frozen(order=True)
class _RecommendedSortKey:
    decile_rank: int
    priority_rank: int
    status_rank: int
    newest_first: float
    report_id: str


def _priority_rank(priority: str | None) -> int:
    values = list(AutonomyPriority.values)
    return values.index(priority) if priority in values else len(values)


def _decile(probability: float | None) -> int | None:
    """The same buckets as `score_decile` in the database."""
    if probability is None:
        return None
    return sum(1 for bound in range(1, _DECILES) if probability * _DECILES >= bound)


def load_predictions(team_id: int, report_ids: Sequence[str]) -> dict[str, ReportPredictions]:
    """The served predictions of each report, in two queries for the whole set."""
    if not report_ids:
        return {}
    scores = {
        str(artefact.report_id): artefact
        for artefact in SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id__in=list(report_ids),
            type=SignalReportArtefact.ArtefactType.RANKING_SCORE,
        )
        .order_by("report_id", "-created_at")
        .distinct("report_id")
    }
    edits = {
        str(row["report_id"]): row["latest"]
        for row in SignalReportArtefact.objects.filter(
            team_id=team_id, report_id__in=list(scores), type__in=EDIT_ARTEFACT_TYPES
        )
        .values("report_id")
        .annotate(latest=Max("created_at"))
    }
    return {report_id: read_report_predictions(scores.get(report_id), edits.get(report_id)) for report_id in report_ids}


def _recommended_for_you(team: Team, user: User, since: datetime.datetime, size: int) -> list[str]:
    """`for_you` reports created since `since`, in the order of `sort=recommended` for this person.

    The view sorts in the database. This reads the person's variant without an exposure, because the
    person is not looking at the inbox, and sorts the few `for_you` reports in Python.
    """
    reports = list(
        reports_for_person(team.id, user)
        .filter(created_at__gte=since)
        .order_by("-updated_at")
        .only("id", "status", "updated_at")[:_FOR_YOU_SCAN_LIMIT]
    )
    if not reports:
        return []
    ranker = resolve_recommended_ranker(team, user, send_feature_flag_events=False)
    return recommended_order(team.id, ranker, reports)[:size]


def recommended_order(team_id: int, ranker: InboxRanker, reports: Sequence[SignalReport]) -> list[str]:
    """Report ids in the order the list view gives `sort=recommended` for `ranker`."""
    ids = [str(report.id) for report in reports]
    priorities = latest_report_priorities(team_id, ids)
    predictions = load_predictions(team_id, ids) if ranker != "priority" else {}

    def sort_key(report: SignalReport) -> _RecommendedSortKey:
        report_id = str(report.id)
        decile = _decile(predictions[report_id].probability(ranker)) if ranker != "priority" else None
        return _RecommendedSortKey(
            # Unscored reports sort after every scored report.
            decile_rank=_DECILES if decile is None else _DECILES - 1 - decile,
            priority_rank=_priority_rank(priorities.get(report_id)),
            status_rank=0 if report.status == SignalReport.Status.READY else 1,
            newest_first=-report.updated_at.timestamp(),
            report_id=report_id,
        )

    return [str(report.id) for report in sorted(reports, key=sort_key)]


def _ids(queryset: QuerySet[SignalReport], size: int) -> list[str]:
    return [str(report_id) for report_id in queryset.values_list("id", flat=True)[:size]]


def _scored_pool(queryset: QuerySet[SignalReport], head: str, size: int) -> list[str]:
    """Reports with a current score for `head`, the highest first. Unscored and stale reports drop out, so EU gives none."""
    return _ids(
        queryset.annotate(_pool_score=latest_ranking_value(head, "scores"))
        .filter(_pool_score__isnull=False)
        .order_by("-_pool_score", "-updated_at", "id"),
        size,
    )


def _priority_pool(queryset: QuerySet[SignalReport], lowest_priority: str, size: int) -> list[str]:
    """Reports with `lowest_priority` or a more urgent one, the most urgent first. A score is not needed."""
    return _ids(
        queryset.annotate(_pool_priority=latest_priority_rank())
        .filter(_pool_priority__lte=AutonomyPriority.values.index(lowest_priority))
        .order_by("_pool_priority", "-updated_at", "id"),
        size,
    )


def _filtered(
    team_reports: QuerySet[SignalReport], team_id: int, pool: CandidatePool, since: datetime.datetime
) -> QuerySet[SignalReport]:
    if pool.actionable_only:
        reports = team_reports.filter(
            status=SignalReport.Status.READY,
            latest_actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value,
            latest_already_addressed=False,
        )
    else:
        reports = (
            team_reports.filter(status__in=_OPEN_STATUSES)
            .exclude(latest_actionability=ActionabilityChoice.NOT_ACTIONABLE.value)
            .exclude(latest_already_addressed=True)
        )
    reports = reports.filter(created_at__gte=since)
    if pool.has_pr is True:
        reports = reports.filter(implementation_pr_report_filter(team_id=team_id))
    elif pool.has_pr is False:
        reports = reports.exclude(implementation_pr_report_filter(team_id=team_id))
    return reports


def _pool_ids(
    team: Team,
    user: User,
    pool: CandidatePool,
    config: PersonalRankingConfig,
    *,
    team_reports: QuerySet[SignalReport],
    now: datetime.datetime,
) -> list[str]:
    since = now - datetime.timedelta(days=pool.window_days or config.window_days)
    match pool.source:
        case "for_you_recommended":
            return _recommended_for_you(team, user, since, pool.size)
        case "for_you_updated":
            return _ids(reports_for_person(team.id, user).order_by("-updated_at", "id"), pool.size)
        case "assigned":
            return _ids(
                team_reports.filter(reports_claimed_for_user(team_id=team.id, user_id=user.id)).order_by(
                    "-updated_at", "id"
                ),
                pool.size,
            )
        case "scored":
            assert pool.head is not None
            return _scored_pool(_filtered(team_reports, team.id, pool, since), pool.head, pool.size)
        case "priority":
            return _priority_pool(_filtered(team_reports, team.id, pool, since), pool.lowest_priority, pool.size)


def _pools(
    team: Team, user: User, config: PersonalRankingConfig, *, now: datetime.datetime, can_view_ranking: bool
) -> list[tuple[str, list[str]]]:
    # The gate-aware filter, because a `monitoring` report reads as resolved while the monitoring gate is off.
    team_reports = SignalReport.objects.filter(team_id=team.id).exclude(
        report_status_filter(EXCLUDED_STATUSES, team_id=team.id)
    )
    return [
        (pool.name, _pool_ids(team, user, pool, config, team_reports=team_reports, now=now))
        for pool in candidate_pools(config)
        # The `scored` pools show the ranking model's order, so only a person who can see the ranking gets them.
        if pool.size and (pool.source != "scored" or can_view_ranking)
    ]


def merge_pools(pools: Sequence[tuple[str, Sequence[str]]], max_candidates: int) -> dict[str, list[str]]:
    """Report ids in pool order, each with every pool that holds it, cut to `max_candidates`."""
    merged: dict[str, list[str]] = {}
    for name, report_ids in pools:
        for report_id in report_ids:
            if report_id in merged:
                merged[report_id].append(name)
            elif len(merged) < max_candidates:
                merged[report_id] = [name]
    return merged


def _needs_you(team_id: int, user: User, reports: Sequence[SignalReport]) -> dict[str, tuple[NeedsYouKind, ...]]:
    ids = [str(report.id) for report in reports]
    named = report_ids_naming_user(team_id=team_id, user=user, report_ids=ids)
    claimed = {
        str(report_id)
        for report_id in SignalReport.objects.filter(team_id=team_id, id__in=ids)
        .filter(reports_claimed_for_user(team_id=team_id, user_id=user.id))
        .values_list("id", flat=True)
    }
    result: dict[str, tuple[NeedsYouKind, ...]] = {}
    for report in reports:
        report_id = str(report.id)
        kinds: list[NeedsYouKind] = []
        if report_id in named and report.status == SignalReport.Status.PENDING_INPUT:
            kinds.append("waiting_on_input")
        if report_id in claimed:
            kinds.append("claimed")
        if report_id in named and report.status == SignalReport.Status.READY:
            kinds.append("suggested_reviewer")
        result[report_id] = tuple(kinds)
    return result


def _clean(text: str | None, limit: int) -> str:
    return " ".join((text or "").split())[:limit]


def gather_candidates(
    team: Team, user: User, config: PersonalRankingConfig, *, now: datetime.datetime, with_sources: bool = True
) -> list[Candidate]:
    """`with_sources=False` skips the ClickHouse read of each report's source, which only the prompt shows."""
    can_view_ranking = can_view_inbox_ranking(user, team)
    merged = merge_pools(_pools(team, user, config, now=now, can_view_ranking=can_view_ranking), config.max_candidates)
    if not merged:
        return []
    ids = list(merged)
    by_id = {
        str(report.id): report
        for report in SignalReport.objects.filter(team_id=team.id, id__in=ids).only(
            "id", "team_id", "title", "summary", "status", "created_at", "updated_at", "tags"
        )
    }
    reports = [by_id[report_id] for report_id in ids if report_id in by_id]
    found = [str(report.id) for report in reports]
    priorities = latest_report_priorities(team.id, found)
    pull_requests = fetch_implementation_pr_state_for_reports(found, team_id=team.id)
    predictions = load_predictions(team.id, found) if can_view_ranking else {}
    needs_you = _needs_you(team.id, user, reports)
    try:
        sources = fetch_source_products_for_reports(team, found) if with_sources else {}
    except Exception:
        # The source is context, so a ClickHouse failure must not stop the ranking.
        logger.exception("signals.personal_ranking.source_products_failed", team_id=team.id)
        sources = {}
    candidates = []
    for index, report in enumerate(reports):
        report_id = str(report.id)
        pull_request = pull_requests.get(report_id)
        source = sources.get(report_id)
        candidates.append(
            Candidate(
                ref=f"c{index + 1}",
                report_id=report_id,
                title=_clean(report.title, _TITLE_MAX_CHARS),
                summary_lead=summary_lead(report.summary, SUMMARY_LEAD_LIMIT),
                status=report.status,
                priority=priorities.get(report_id),
                pull_request_state=implementation_pull_request_state(pull_request.state, pull_request.merged)
                if pull_request
                else None,
                source_products=tuple(source.source_products) if source else (),
                scout_name=source.scout_name if source else None,
                created_at=report.created_at,
                updated_at=report.updated_at,
                predictions=predictions.get(report_id) if can_view_ranking else None,
                needs_you=needs_you.get(report_id, ()),
                tags=tuple(report.tags or ()),
                pools=tuple(merged[report_id]),
            )
        )
    return candidates
