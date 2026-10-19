"""Reports that matter to one person, for the Today briefing.

This module answers "which reports relate to this person, and how". The inbox `for_you` list
orders these reports with the inbox priority order.
"""

import re
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from django.db.models import Case, CharField, F, Func, JSONField, OuterRef, Q, QuerySet, Subquery, Value, When
from django.db.models.functions import Cast

from posthog.dataclasses import frozen
from posthog.models import User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ActionabilityChoice, priority_from_judgment
from products.signals.backend.implementation_pr import (
    fetch_implementation_pr_state_for_reports,
    implementation_pr_report_filter,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignment
from products.signals.backend.report_charts import ReportChartSnapshot, saved_charts
from products.signals.backend.report_claims import reports_with_active_claim
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_lifecycle import effective_report_status
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy
from products.signals.backend.report_metrics import ReportMetricSnapshot, saved_metric_snapshots
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers

_OPEN_STATUSES = (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)
# The hover card shows more of the summary than the briefing writer reads.
SUMMARY_LEAD_LIMIT = 450


class BriefingReportRelation(StrEnum):
    """How a report relates to the person, strongest first: what blocks on them, what they own,
    what names them, then what nobody owns. A report keeps the first relation that matches."""

    WAITING_FOR_YOU = "waiting_for_you"
    CLAIMED = "claimed"
    SUGGESTED_REVIEWER = "suggested_reviewer"
    URGENT_UNOWNED = "urgent_unowned"


# The implementation pull request states a briefing shows. `unknown` reads as no state.
IMPLEMENTATION_PR_STATES: tuple[str, ...] = tuple(
    state for state in SignalReportAssignment.PrState.values if state != SignalReportAssignment.PrState.UNKNOWN
)


@frozen
class BriefingReportDetails:
    """The current state of a report a briefing names, read live so a briefing written earlier stays true."""

    report_id: str
    status: str
    priority: str | None
    summary: str
    # One of IMPLEMENTATION_PR_STATES, or None when the report has no implementation PR.
    pull_request_state: str | None
    pull_request_url: str | None
    signal_count: int
    updated_at: datetime
    # Only metrics with a saved snapshot, so the briefing shows a figure before the live query answers.
    metrics: list[ReportMetricSnapshot]
    charts: list[ReportChartSnapshot]


def _latest_artefacts(team_id: int, report_ids: Sequence[str], artefact_type: str) -> dict[str, str]:
    """The newest artefact content of one type per report, by report id."""
    # Pick the newest id per report first, so Postgres reads `content` once per report, not once per row.
    latest_ids = (
        SignalReportArtefact.objects.filter(team_id=team_id, report_id__in=report_ids, type=artefact_type)
        .order_by("report_id", "-created_at")
        .distinct("report_id")
        .values("id")
    )
    rows = SignalReportArtefact.objects.filter(team_id=team_id, id__in=latest_ids).values_list("report_id", "content")
    return {str(report_id): content for report_id, content in rows}


def _priorities(team_id: int, report_ids: Sequence[str]) -> dict[str, str]:
    """Latest priority judgment per report, read the same way the inbox serializer reads it."""
    latest: dict[str, str] = {}
    for report_id, content in _latest_artefacts(
        team_id, report_ids, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
    ).items():
        priority = priority_from_judgment(content)
        if priority is not None:
            latest[report_id] = priority
    return latest


def _json_object_content() -> Q:
    # Content is written from a pydantic schema. The guard only keeps a legacy or truncated row out
    # of the jsonb cast, because a failed cast fails the whole query.
    return Q(content__startswith="{", content__endswith="}")


def _latest_priority() -> Subquery:
    """The priority of each report's latest priority judgment, as text. The latest row decides, so
    a malformed latest row reads as no priority, as `priority_from_judgment` reads it."""
    priority = Func(
        Cast(F("content"), output_field=JSONField()),
        Value("priority"),
        function="jsonb_extract_path_text",
        output_field=CharField(),
    )
    return Subquery(
        SignalReportArtefact.objects.filter(
            report_id=OuterRef("id"), type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
        )
        .order_by("-created_at")
        .annotate(
            _priority=Case(When(_json_object_content(), then=priority), default=Value(None), output_field=CharField())
        )
        .values("_priority")[:1],
        output_field=CharField(),
    )


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


def report_ids_naming_user(*, team_id: int, user: User, report_ids: Sequence[str]) -> set[str]:
    """Which of these reports still name the person as a suggested reviewer.

    A briefing is a saved list, so an item it picked because the report named the person can outlive
    that fact. Reading membership live is what lets a reader tell a report they stepped off from one
    that is still theirs.
    """
    if not report_ids:
        return set()
    github_login = user.get_github_login()
    naming = report_ids_naming_reviewers(
        team_id=team_id,
        user_uuids=[str(user.uuid)],
        github_logins=[github_login.lower()] if github_login else [],
        logins_match_unidentified_only=False,
    ).filter(report_id__in=list(report_ids))
    return {str(row["report_id"]) for row in naming}


def _relation_to_person(team_id: int, user: User, *, include_unowned: bool) -> Case:
    """A report's strongest `BriefingReportRelation` to the person, or NULL when it has none.

    Reads the `briefing_priority` annotation, so the queryset must carry `_latest_priority()` first.
    `include_unowned` decides whether a P0 nobody owns counts as a relation. It belongs to the project
    rather than to the person, so a surface that only pushes a person's own work leaves it out. Leaving
    it out also drops the claim and implementation-PR subqueries from the expression, which Postgres
    evaluates for every open report before the relation filter applies.
    """
    names_me = _names_person(team_id, user)
    claimed = reports_with_active_claim(team_id=team_id, actor=ArtefactAttribution.from_user(user.id))
    branches = [
        When(
            names_me & Q(status=SignalReport.Status.PENDING_INPUT), then=Value(BriefingReportRelation.WAITING_FOR_YOU)
        ),
        When(claimed, then=Value(BriefingReportRelation.CLAIMED)),
        When(names_me & Q(status=SignalReport.Status.READY), then=Value(BriefingReportRelation.SUGGESTED_REVIEWER)),
    ]
    if include_unowned:
        unowned = ~reports_with_active_claim(team_id=team_id) & ~implementation_pr_report_filter(
            team_id=team_id, active_only=True
        )
        branches.append(
            When(
                unowned
                & Q(
                    status=SignalReport.Status.READY,
                    latest_actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE.value,
                    briefing_priority="P0",
                ),
                then=Value(BriefingReportRelation.URGENT_UNOWNED),
            )
        )
    return Case(*branches, default=Value(None), output_field=CharField())


def reports_for_person(team_id: int, user: User, *, include_unowned: bool) -> QuerySet[SignalReport]:
    """The open reports that are for this person: the set the inbox `for_you` list ranks and counts."""
    return (
        _open_reports(team_id)
        .annotate(briefing_priority=_latest_priority())
        .annotate(briefing_relation=_relation_to_person(team_id, user, include_unowned=include_unowned))
        .filter(briefing_relation__isnull=False)
    )


@frozen
class OpenReportCounts:
    for_person: int
    in_project: int


def open_report_counts(
    *, team_id: int, user: User, exclude_report_ids: Sequence[str] = (), include_unowned: bool = True
) -> OpenReportCounts:
    """How many open, actionable reports the project has, and how many of them are for this person.

    `for_person` counts the set `reports_for_person` returns, so a "more for you" number agrees
    with the list it follows; pass the `include_unowned` the list was built with to keep that true.
    `in_project` ignores the relation either way, so a P0 nobody owns is still counted there.
    `exclude_report_ids` leaves out the reports already on screen; one that is resolved or not for the
    person was never in the set, so it is not subtracted from it.
    """
    excluded = list(exclude_report_ids)
    in_project = _open_reports(team_id).exclude(id__in=excluded).count()
    for_person = reports_for_person(team_id, user, include_unowned=include_unowned).exclude(id__in=excluded).count()
    return OpenReportCounts(for_person=for_person, in_project=in_project)


def _pull_request_state(state: str, merged: bool) -> str | None:
    if merged:
        return SignalReportAssignment.PrState.MERGED
    return state if state in IMPLEMENTATION_PR_STATES else None


def _trimmed(text: str | None, limit: int) -> str:
    return " ".join((text or "").split())[:limit]


_MARKDOWN_HEADING_LINE = re.compile(r"^ {0,3}#{1,6}(?:[ \t].*)?$", re.MULTILINE)
# A `chart:` link places a chart in the report body. Plain text has no chart to place, so the link goes.
# Load-bearing: the label and destination classes exclude `[`. Without that, a summary of unclosed
# brackets makes each start position rescan the rest of the text, which costs seconds per summary.
_MARKDOWN_CHART_LINK = re.compile(r"\[[^\[\]]*\]\(chart:[^)\[]*\)")
_MARKDOWN_CHART_ID = re.compile(r"\]\(chart:([^)\s\[]+)\)")
_MARKDOWN_LINK = re.compile(r"\[([^\[\]]*)\]\([^)\[]*\)")
# Only `**` and backticks: `__` also appears inside identifiers such as `__init__` or `team__id`.
_MARKDOWN_EMPHASIS = re.compile(r"\*\*|`")


def summary_lead(summary: str | None, limit: int) -> str:
    """The opening of a report's markdown summary as plain text on one line: the text before its first
    section heading, with chart links removed and other links reduced to their text."""
    sections = _MARKDOWN_HEADING_LINE.split(summary or "")
    lead = next((section for section in sections if section.strip()), "")
    lead = _MARKDOWN_CHART_LINK.sub("", lead)
    lead = _MARKDOWN_LINK.sub(r"\1", lead)
    return _trimmed(_MARKDOWN_EMPHASIS.sub("", lead), limit)


def _charts_by_reference(charts: list[ReportChartSnapshot], summary: str | None) -> list[ReportChartSnapshot]:
    """The charts the summary references, in the order it references them, then the rest in stored order."""
    referenced = list(dict.fromkeys(_MARKDOWN_CHART_ID.findall(summary or "")))
    rank = {chart_id: index for index, chart_id in enumerate(referenced)}
    return sorted(charts, key=lambda chart: rank.get(chart.chart_id, len(rank)))


def report_details(
    *, team_id: int, report_ids: Sequence[str], metric_access: ReportMetricAccessPolicy
) -> list[BriefingReportDetails]:
    """Current status, priority, summary, implementation PR and metric snapshots of the given reports.

    A briefing written earlier reads these live, so it shows which reports are done and what changed.
    Only the metrics whose snapshot `metric_access` lets the viewer read are returned, as in the Inbox.
    """
    if not report_ids:
        return []
    reports = list(
        SignalReport.objects.filter(team_id=team_id, id__in=list(report_ids)).only(
            "id", "team_id", "status", "summary", "metrics", "charts", "signal_count", "updated_at"
        )
    )
    found_ids = [str(report.id) for report in reports]
    priorities = _priorities(team_id, found_ids)
    pull_requests = fetch_implementation_pr_state_for_reports(found_ids, team_id=team_id)
    monitoring_enabled = (
        team_report_monitoring_enabled(team_id)
        if any(report.status == SignalReport.Status.MONITORING for report in reports)
        else None
    )
    details = []
    for report in reports:
        report_id = str(report.id)
        pull_request = pull_requests.get(report_id)
        details.append(
            BriefingReportDetails(
                report_id=report_id,
                status=effective_report_status(report.status, team_id=team_id, monitoring_enabled=monitoring_enabled),
                priority=priorities.get(report_id),
                summary=summary_lead(report.summary, SUMMARY_LEAD_LIMIT),
                pull_request_state=_pull_request_state(pull_request.state, pull_request.merged)
                if pull_request
                else None,
                pull_request_url=pull_request.url if pull_request else None,
                signal_count=report.signal_count,
                updated_at=report.updated_at,
                metrics=saved_metric_snapshots(report.metrics, metric_access),
                charts=_charts_by_reference(saved_charts(report.charts), report.summary),
            )
        )
    return details
