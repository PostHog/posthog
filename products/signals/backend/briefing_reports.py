"""Reports that matter to one person, for the Today briefing.

The briefing ranks items across products, so this module only answers "which reports relate to this
person, and how". It does not order across relations; the caller does that.
"""

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Literal

from django.db.models import Count, Q, QuerySet

import pydantic
import structlog

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ActionabilityChoice, RankingScore, priority_from_judgment
from products.signals.backend.implementation_pr import (
    fetch_implementation_pr_state_for_reports,
    implementation_pr_report_filter,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_claims import reports_with_active_claim
from products.signals.backend.report_metrics import (
    ReportMetric,
    ReportMetricKind,
    ReportMetricRole,
    ReportMetricValueFormat,
)
from products.signals.backend.signal_metadata import fetch_source_products_for_reports
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers

logger = structlog.get_logger(__name__)

_OPEN_STATUSES = (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)
_SUMMARY_LIMIT = 300
PR_MERGED_HEAD = "pr_merged"


class BriefingReportRelation(StrEnum):
    """How a report relates to the person, strongest first: what blocks on them, what they own,
    what names them, then what nobody owns. A report keeps the first relation that matches."""

    WAITING_FOR_YOU = "waiting_for_you"
    CLAIMED = "claimed"
    SUGGESTED_REVIEWER = "suggested_reviewer"
    URGENT_UNOWNED = "urgent_unowned"


_RELATION_ORDER = {relation: index for index, relation in enumerate(BriefingReportRelation)}
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


@frozen
class BriefingReport:
    report_id: str
    relation: BriefingReportRelation
    title: str
    summary: str
    status: str
    priority: str | None
    has_implementation_pr: bool
    # The products the report's signals came from, sorted, the way the inbox list shows them.
    source_products: list[str]
    updated_at: datetime
    # The served ranking model's chance that the report ends with a merged PR. None when the
    # report has no score yet, or the model's pr_merged head is not readable.
    pr_merged_probability: float | None


PullRequestState = Literal["draft", "open", "closed", "merged"]


@frozen
class BriefingReportMetric:
    """A report metric's saved snapshot, in the shape the inbox list shows it. Never the live query."""

    metric_id: str
    title: str
    kind: ReportMetricKind
    role: ReportMetricRole
    value: float
    value_at: datetime | None
    series: list[float] | None
    value_format: ReportMetricValueFormat
    unit: str | None


@frozen
class BriefingReportDetails:
    """The current state of a report a briefing names, read live so a briefing written earlier stays true."""

    report_id: str
    status: str
    priority: str | None
    summary: str
    pull_request_state: PullRequestState | None
    pull_request_url: str | None
    # Only metrics with a saved snapshot: the briefing shows figures, it never runs a query.
    metrics: list[BriefingReportMetric]


def _latest_artefacts(report_ids: Sequence[str], artefact_type: str) -> dict[str, str]:
    """The newest artefact content of one type per report, by report id."""
    rows = (
        SignalReportArtefact.objects.filter(report_id__in=report_ids, type=artefact_type)
        .order_by("report_id", "-created_at")
        .distinct("report_id")
        .values_list("report_id", "content")
    )
    return {str(report_id): content for report_id, content in rows}


def _priorities(report_ids: Sequence[str]) -> dict[str, str]:
    """Latest priority judgment per report, read the same way the inbox serializer reads it."""
    latest: dict[str, str] = {}
    for report_id, content in _latest_artefacts(
        report_ids, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
    ).items():
        priority = priority_from_judgment(content)
        if priority is not None:
            latest[report_id] = priority
    return latest


def _pr_merged_probabilities(report_ids: Sequence[str]) -> dict[str, float]:
    """The served model's `pr_merged` probability from each report's latest score.

    A head without a holdout AUC is not readable, so its probability is left out rather than
    trusted. The inbox serializer applies the same readability rule.
    """
    from products.signals.backend.ranking.model_contract import (  # noqa: PLC0415 — keeps numpy and pandas off the facade import path
        readable_head_names,
    )

    probabilities: dict[str, float] = {}
    for report_id, content in _latest_artefacts(report_ids, SignalReportArtefact.ArtefactType.RANKING_SCORE).items():
        try:
            score = RankingScore.model_validate_json(content)
        except pydantic.ValidationError:
            logger.warning("signals.briefing.ranking_score_unreadable", report_id=report_id)
            continue
        served = score.results[score.served_key]
        probability = served.scores.get(PR_MERGED_HEAD)
        if probability is not None and PR_MERGED_HEAD in readable_head_names(served.metadata):
            probabilities[report_id] = probability
    return probabilities


def _open_reports(team_id: int) -> QuerySet[SignalReport]:
    """The reports the briefing may show and count: open, judged actionable, not already addressed."""
    return (
        SignalReport.objects.filter(team_id=team_id, status__in=_OPEN_STATUSES)
        .exclude(latest_actionability=ActionabilityChoice.NOT_ACTIONABLE.value)
        .exclude(latest_already_addressed=True)
    )


def _names_person(team_id: int, user: User) -> Q:
    github_login = user.get_github_login()
    return Q(
        id__in=report_ids_naming_reviewers(
            team_id=team_id,
            user_uuids=[str(user.uuid)],
            github_logins=[github_login.lower()] if github_login else [],
            logins_match_unidentified_only=False,
        )
    )


def _source_products(team_id: int, report_ids: Sequence[str]) -> dict[str, list[str]]:
    """Per report, the products its signals came from. A ClickHouse failure costs the colors, not the reports."""
    if not report_ids:
        return {}
    try:
        metadata = fetch_source_products_for_reports(Team.objects.get(id=team_id), list(report_ids))
    except Exception:
        logger.warning("signals.briefing.source_products_unavailable", team_id=team_id, exc_info=True)
        return {}
    return {report_id: meta.source_products for report_id, meta in metadata.items()}


def _briefing_order(
    relation: BriefingReportRelation, priority: str | None, merge_chance: float | None, updated_at: datetime
) -> tuple[float, ...]:
    """Relation first. Inside a relation: P0, then the higher chance of a merged PR, then priority,
    then newest. A report without a score follows the scored ones, so with no scores at all the
    order falls back to priority."""
    return (
        _RELATION_ORDER[relation],
        0 if priority == "P0" else 1,
        0 if merge_chance is not None else 1,
        -(merge_chance or 0.0),
        _PRIORITY_ORDER.get(priority or "", 5),
        -updated_at.timestamp(),
    )


def reports_for_briefing(
    *, team_id: int, user_id: int, limit_per_relation: int = 5, limit: int | None = None
) -> list[BriefingReport]:
    """Open, actionable reports for one person, in briefing order, each tagged with its strongest relation.

    A report appears once, under the first `BriefingReportRelation` that matches. Each relation
    contributes its newest `limit_per_relation` rows (more for urgent-unowned, which is filtered to
    P0 afterwards) to the candidate set; `limit` then keeps the best of the ranked set.
    """
    open_reports = _open_reports(team_id)
    names_me = _names_person(team_id, User.objects.get(id=user_id))
    claimed = reports_with_active_claim(team_id=team_id, actor=ArtefactAttribution.from_user(user_id))
    unowned = ~reports_with_active_claim(team_id=team_id) & ~implementation_pr_report_filter(
        team_id=team_id, active_only=True
    )
    buckets: list[tuple[BriefingReportRelation, Q]] = [
        (BriefingReportRelation.WAITING_FOR_YOU, names_me & Q(status=SignalReport.Status.PENDING_INPUT)),
        (BriefingReportRelation.CLAIMED, claimed),
        (BriefingReportRelation.SUGGESTED_REVIEWER, names_me & Q(status=SignalReport.Status.READY)),
        (
            BriefingReportRelation.URGENT_UNOWNED,
            unowned
            & Q(
                status=SignalReport.Status.READY,
                latest_actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value,
            ),
        ),
    ]
    seen: set[str] = set()
    picked: list[tuple[BriefingReportRelation, SignalReport]] = []
    for relation, condition in buckets:
        # Urgent-unowned is only meaningful at P0, which is filtered after the priority lookup,
        # so it reads a wider page than the other buckets.
        page = limit_per_relation * 4 if relation == BriefingReportRelation.URGENT_UNOWNED else limit_per_relation
        for report in open_reports.filter(condition).order_by("-updated_at")[:page]:
            key = str(report.id)
            if key not in seen:
                seen.add(key)
                picked.append((relation, report))
    # Priorities decide which urgent-unowned rows survive, so they load for every picked row; the
    # other lookups only feed the rows that make it into the result.
    priorities = _priorities([str(report.id) for _, report in picked])
    chosen = [
        (relation, report)
        for relation, report in picked
        if relation != BriefingReportRelation.URGENT_UNOWNED or priorities.get(str(report.id)) == "P0"
    ]
    merge_chances = _pr_merged_probabilities([str(report.id) for _, report in chosen])
    # Rank the whole candidate set before any limit, so a sixth report that waits for the person
    # outranks the first claimed one instead of falling off its own bucket.
    chosen.sort(
        key=lambda pair: _briefing_order(
            pair[0], priorities.get(str(pair[1].id)), merge_chances.get(str(pair[1].id)), pair[1].updated_at
        )
    )
    if limit is not None:
        chosen = chosen[:limit]
    chosen_ids = [str(report.id) for _, report in chosen]
    source_products = _source_products(team_id, chosen_ids)
    with_pr = set(
        SignalReport.objects.filter(team_id=team_id, id__in=chosen_ids)
        .filter(implementation_pr_report_filter(team_id=team_id))
        .values_list("id", flat=True)
    )
    return [
        BriefingReport(
            report_id=str(report.id),
            relation=relation,
            title=" ".join((report.title or "").split())[:200] or "Untitled report",
            summary=" ".join((report.summary or "").split())[:_SUMMARY_LIMIT],
            status=report.status,
            priority=priorities.get(str(report.id)),
            has_implementation_pr=report.id in with_pr,
            source_products=source_products.get(str(report.id), []),
            updated_at=report.updated_at,
            pr_merged_probability=merge_chances.get(str(report.id)),
        )
        for relation, report in chosen
    ]


@frozen
class OpenReportCounts:
    for_person: int
    in_project: int


def open_report_counts(*, team_id: int, user: User, exclude_report_ids: Sequence[str] = ()) -> OpenReportCounts:
    """How many open, actionable reports the project has, and how many of them name this person.

    `exclude_report_ids` leaves out the reports a briefing already shows; one that is resolved or
    does not name the person was never in the set, so it is not subtracted from it.
    """
    row = (
        _open_reports(team_id)
        .exclude(id__in=list(exclude_report_ids))
        .aggregate(in_project=Count("id"), for_person=Count("id", filter=_names_person(team_id, user)))
    )
    return OpenReportCounts(for_person=row["for_person"], in_project=row["in_project"])


def _snapshot_metrics(raw_metrics: object) -> list[BriefingReportMetric]:
    if not isinstance(raw_metrics, list):
        return []
    metrics: list[BriefingReportMetric] = []
    for raw in raw_metrics:
        try:
            metric = ReportMetric.model_validate(raw)
        except pydantic.ValidationError:
            continue
        if metric.value is None:
            continue
        metrics.append(
            BriefingReportMetric(
                metric_id=metric.metric_id,
                title=metric.title,
                kind=metric.kind,
                role=metric.role,
                value=metric.value,
                value_at=metric.value_at,
                series=metric.series,
                value_format=metric.value_format,
                unit=metric.unit,
            )
        )
    return metrics


def _pull_request_state(state: str, merged: bool) -> PullRequestState | None:
    if merged:
        return "merged"
    match state:
        case "draft" | "open" | "closed" | "merged":
            return state
        case _:
            return None


def report_details(*, team_id: int, report_ids: Sequence[str]) -> list[BriefingReportDetails]:
    """Current status, priority, summary, implementation PR and metric snapshots of the given reports.

    A briefing written earlier reads these live, so it shows which reports are done and what changed.
    """
    if not report_ids:
        return []
    reports = list(
        SignalReport.objects.filter(team_id=team_id, id__in=list(report_ids)).only("id", "status", "summary", "metrics")
    )
    found_ids = [str(report.id) for report in reports]
    priorities = _priorities(found_ids)
    pull_requests = fetch_implementation_pr_state_for_reports(found_ids, team_id=team_id)
    details = []
    for report in reports:
        report_id = str(report.id)
        pull_request = pull_requests.get(report_id)
        details.append(
            BriefingReportDetails(
                report_id=report_id,
                status=report.status,
                priority=priorities.get(report_id),
                summary=" ".join((report.summary or "").split())[:_SUMMARY_LIMIT],
                pull_request_state=_pull_request_state(pull_request.state, pull_request.merged)
                if pull_request
                else None,
                pull_request_url=pull_request.url if pull_request else None,
                metrics=_snapshot_metrics(report.metrics),
            )
        )
    return details
