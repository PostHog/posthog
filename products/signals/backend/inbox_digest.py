"""A small, fixed-size read of one person's inbox: what needs them now, and what changed for them since a time.

It reads Postgres only, in a fixed number of queries whatever the size of the inbox.
"""

from collections import Counter
from datetime import datetime, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.briefing_reports import (
    BriefingReportRelation,
    implementation_pull_request_state,
    relation_of,
    reports_connected_to_person,
    reports_for_person,
    summary_lead,
)
from products.signals.backend.implementation_pr import fetch_implementation_pr_state_for_reports
from products.signals.backend.inbox_list_filters import actionable_condition, unclaimed_condition
from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalReportPullRequest,
)
from products.signals.backend.personal_ranking.candidates import priority_order
from products.signals.backend.report_content_gates import (
    organization_inbox_cached_filters_enabled,
    organization_report_monitoring_enabled,
)
from products.signals.backend.report_monitoring_summary import MonitoringOutcomeKind, monitoring_outcomes
from products.signals.backend.report_priority import latest_report_priorities
from products.signals.backend.report_urls import ReportLinkSource, build_bare_report_url, build_report_url
from products.signals.backend.scout_authorship import inbox_hidden_report_filter

DEFAULT_LOOKBACK = timedelta(days=1)
MAX_LOOKBACK = timedelta(days=30)
REPORTS_PER_SECTION = 3
SUMMARY_LEAD_CHARS = 200


@frozen
class InboxDigestReport:
    id: str
    title: str | None
    # One of AutonomyPriority, or None when the report has no priority judgment.
    priority: str | None
    status: str
    relation: BriefingReportRelation
    summary_lead: str
    implementation_pr_url: str | None
    # One of IMPLEMENTATION_PR_STATES, or None when the report has no implementation PR or its state is unknown.
    implementation_pr_state: str | None
    url: str


@frozen
class InboxDigestSection:
    count: int
    reports: tuple[InboxDigestReport, ...]


@frozen
class InboxDigestMonitoringOutcome:
    # One of MonitoringOutcomeKind.
    outcome: str
    count: int


@frozen
class InboxDigestOutcomes:
    pull_requests_opened: int
    pull_requests_merged: int
    # None when the organization does not have Monitoring.
    monitoring_periods_ended: tuple[InboxDigestMonitoringOutcome, ...] | None


@frozen
class InboxDigestProject:
    actionable_unclaimed_count: int


@frozen
class InboxDigest:
    since: datetime
    generated_at: datetime
    needs_you: InboxDigestSection
    new_for_you: InboxDigestSection
    outcomes: InboxDigestOutcomes
    project: InboxDigestProject


def digest_since(requested: datetime | None, now: datetime) -> datetime:
    """Where the digest's window starts: one day back by default, never more than 30 days back, never after now."""
    if requested is None:
        return now - DEFAULT_LOOKBACK
    return min(max(requested, now - MAX_LOOKBACK), now)


def _compact_reports(
    team_id: int, reports: list[SignalReport], link_source: ReportLinkSource | None
) -> dict[str, InboxDigestReport]:
    ids = [str(report.id) for report in reports]
    if not ids:
        return {}
    content = {
        str(row["id"]): row
        for row in SignalReport.objects.filter(team_id=team_id, id__in=ids).values("id", "title", "summary")
    }
    priorities = latest_report_priorities(team_id, ids)
    pull_requests = fetch_implementation_pr_state_for_reports(ids, team_id=team_id)
    compact: dict[str, InboxDigestReport] = {}
    for report in reports:
        report_id = str(report.id)
        row = content.get(report_id)
        if row is None:
            continue
        priority = priorities.get(report_id)
        pull_request = pull_requests.get(report_id)
        compact[report_id] = InboxDigestReport(
            id=report_id,
            title=row["title"],
            priority=priority if priority in AutonomyPriority.values else None,
            status=report.status,
            relation=relation_of(report),
            summary_lead=summary_lead(row["summary"], SUMMARY_LEAD_CHARS),
            implementation_pr_url=pull_request.url if pull_request else None,
            implementation_pr_state=implementation_pull_request_state(pull_request.state, pull_request.merged)
            if pull_request
            else None,
            url=build_report_url(team_id, report_id, link_source)
            if link_source is not None
            else build_bare_report_url(team_id, report_id),
        )
    return compact


def _outcomes(team: Team, user: User, since: datetime) -> InboxDigestOutcomes:
    connected = (
        SignalReport.objects.filter(team_id=team.id)
        .exclude(status=SignalReport.Status.DELETED)
        .filter(reports_connected_to_person(team.id, user))
    )
    linked_pull_requests = SignalReportArtefact.objects.filter(
        team_id=team.id,
        type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
        report_id__in=connected.values("id"),
    ).values("pull_request_id")
    pull_requests = (
        SignalReportPullRequest.objects.for_team(team.id)
        .filter(id__in=linked_pull_requests)
        .filter(Q(created_at__gte=since) | Q(merged_at__gte=since))
        .aggregate(
            opened=Count("id", filter=Q(created_at__gte=since)),
            merged=Count("id", filter=Q(state=SignalReportPullRequest.State.MERGED, merged_at__gte=since)),
        )
    )
    monitoring: tuple[InboxDigestMonitoringOutcome, ...] | None = None
    if organization_report_monitoring_enabled(team.organization_id):
        ended = list(
            connected.filter(
                status__in=[SignalReport.Status.RESOLVED, SignalReport.Status.CLOSED],
                monitoring_started_at__isnull=False,
                monitoring_ended_at__gte=since,
            ).only("id", "team_id", "status", "monitoring_started_at", "monitoring_ended_at")
        )
        kinds = Counter(outcome.kind for outcome in monitoring_outcomes(ended, team_id=team.id).values())
        monitoring = tuple(
            InboxDigestMonitoringOutcome(outcome=kind.value, count=kinds[kind])
            for kind in MonitoringOutcomeKind
            if kinds[kind]
        )
    return InboxDigestOutcomes(
        pull_requests_opened=pull_requests["opened"],
        pull_requests_merged=pull_requests["merged"],
        monitoring_periods_ended=monitoring,
    )


def _actionable_unclaimed_count(team: Team) -> int:
    cached = organization_inbox_cached_filters_enabled(team.organization_id)
    return (
        SignalReport.objects.filter(team_id=team.id)
        .filter(inbox_hidden_report_filter(team.id))
        .filter(
            actionable_condition(team_id=team.id, cached=cached), unclaimed_condition(team_id=team.id, cached=cached)
        )
        .count()
    )


def get_inbox_digest(
    *, team: Team, user: User, since: datetime | None, link_source: ReportLinkSource | None
) -> InboxDigest:
    """The person's digest. `needs_you` is the current state, while `new_for_you` and `outcomes` count from `since`.

    `link_source` tags the report links for the inbox's open analytics. Without it the links are bare.
    """
    now = timezone.now()
    window_start = digest_since(since, now)
    personal = {
        str(report.id): report
        for report in reports_for_person(team.id, user).only("id", "status", "updated_at", "first_visible_at")
    }
    ordered = priority_order(team.id, list(personal.values()))
    # `first_visible_at` is set once, when a report first reaches the inbox, so a reopened report is not new again.
    new = [
        report_id
        for report_id in ordered
        if (first_visible_at := personal[report_id].first_visible_at) is not None and first_visible_at >= window_start
    ]
    shown = list(dict.fromkeys([*ordered[:REPORTS_PER_SECTION], *new[:REPORTS_PER_SECTION]]))
    compact = _compact_reports(team.id, [personal[report_id] for report_id in shown], link_source)
    return InboxDigest(
        since=window_start,
        generated_at=now,
        needs_you=InboxDigestSection(
            count=len(ordered),
            reports=tuple(compact[report_id] for report_id in ordered[:REPORTS_PER_SECTION] if report_id in compact),
        ),
        new_for_you=InboxDigestSection(
            count=len(new),
            reports=tuple(compact[report_id] for report_id in new[:REPORTS_PER_SECTION] if report_id in compact),
        ),
        outcomes=_outcomes(team, user, window_start),
        project=InboxDigestProject(actionable_unclaimed_count=_actionable_unclaimed_count(team)),
    )
