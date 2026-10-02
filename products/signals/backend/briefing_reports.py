"""Reports that matter to one person, for the Today briefing.

This module answers "which reports relate to this person, and how", and orders them with the
served ranking model. The Today briefing and the inbox `for_you` list share this order.
"""

import re
import math
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from fractions import Fraction

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
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignment
from products.signals.backend.report_charts import ReportChartSnapshot, saved_charts
from products.signals.backend.report_claims import reports_with_active_claim
from products.signals.backend.report_metric_access import ReportMetricAccessPolicy
from products.signals.backend.report_metrics import ReportMetricSnapshot, saved_metric_snapshots
from products.signals.backend.signal_metadata import fetch_source_products_for_reports
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers

logger = structlog.get_logger(__name__)

_OPEN_STATUSES = (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)
_SUMMARY_LIMIT = 300
# The hover card shows more of the summary than the briefing writer reads.
SUMMARY_LEAD_LIMIT = 450
PR_MERGED_HEAD = "pr_merged"
ACTION_HEAD = "action"
DISMISS_WRONG_HEAD = "dismiss_wrong"
# A report the model expects to be dismissed as wrong at this many times the head's base rate is
# left out. The rule only applies to a model that saved a classification threshold for the head,
# because a raw probability is not calibrated and changes meaning with each model version.
DISMISS_WRONG_HIDE_LIFT = 3.0
# The share of the slots after P0 that goes to the reports waiting for the person, rounded up so the
# first slot is always theirs. The rest goes to the reports most likely to end with a merged PR, so
# the input queue cannot fill the whole list. A Fraction keeps the rounding exact.
NEEDS_YOU_SHARE = Fraction(2, 5)
# A bound on the reports each relation reads, so one person with a very large inbox cannot make
# the briefing slow. It is far above the number of open reports a person usually has.
_CANDIDATES_PER_RELATION = 200


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


@frozen
class _ServedScores:
    """The readable heads of a report's latest served score that the briefing ranks on."""

    pr_merged: float | None
    action: float | None
    dismiss_wrong_lift: float | None


def _served_scores(report_ids: Sequence[str]) -> dict[str, _ServedScores]:
    """The served model's probabilities from each report's latest score.

    A head without a holdout AUC is not readable, so its probability is left out rather than
    trusted. The inbox serializer applies the same readability rule.
    """
    from products.signals.backend.ranking.model_contract import (  # noqa: PLC0415 — keeps numpy and pandas off the facade import path
        head_lifts,
        readable_head_names,
    )

    scores: dict[str, _ServedScores] = {}
    for report_id, content in _latest_artefacts(report_ids, SignalReportArtefact.ArtefactType.RANKING_SCORE).items():
        try:
            score = RankingScore.model_validate_json(content)
        except pydantic.ValidationError:
            logger.warning("signals.briefing.ranking_score_unreadable", report_id=report_id)
            continue
        served = score.results[score.served_key]
        readable = readable_head_names(served.metadata)
        # A score written before lifts were stored carries the metadata to compute them.
        lifts = served.lifts or head_lifts(served.scores, served.metadata)
        scores[report_id] = _ServedScores(
            pr_merged=served.scores.get(PR_MERGED_HEAD) if PR_MERGED_HEAD in readable else None,
            action=served.scores.get(ACTION_HEAD) if ACTION_HEAD in readable else None,
            dismiss_wrong_lift=lifts.get(DISMISS_WRONG_HEAD) if DISMISS_WRONG_HEAD in readable else None,
        )
    return scores


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


_NO_SCORES = _ServedScores(pr_merged=None, action=None, dismiss_wrong_lift=None)


@frozen
class _BriefingCandidate:
    report_id: str
    relation: BriefingReportRelation
    priority: str | None
    updated_at: datetime
    scores: _ServedScores


def _lane_order(priority: str | None, chance: float | None, updated_at: datetime) -> tuple[float, ...]:
    """The higher chance first, then priority, then newest. A report without a score follows the
    scored ones, so with no scores at all the order falls back to priority."""
    return (
        0 if chance is not None else 1,
        -(chance or 0.0),
        _PRIORITY_ORDER.get(priority or "", 5),
        -updated_at.timestamp(),
    )


def _likely_dismissed_as_wrong(candidate: _BriefingCandidate) -> bool:
    # A P0 always shows, because a missed real P0 costs more than one wrong item in the list.
    lift = candidate.scores.dismiss_wrong_lift
    return candidate.priority != "P0" and lift is not None and lift >= DISMISS_WRONG_HIDE_LIFT


def _briefing_pick(candidates: Sequence[_BriefingCandidate], limit: int | None) -> list[_BriefingCandidate]:
    """P0 reports first. Then the reports that wait for the person's input, by the chance that they
    act on it. Then the reports they can ship, by the chance of a merged PR.

    A report waiting for input needs a decision, not a merge, so its merge chance says little about
    it. With a `limit`, the waiting reports get `NEEDS_YOU_SHARE` of the slots left after P0, and a
    lane with too few reports gives its free slots to the other lane.
    """
    kept = [c for c in candidates if not _likely_dismissed_as_wrong(c)]
    urgent = sorted(
        (c for c in kept if c.priority == "P0"),
        key=lambda c: (_RELATION_ORDER[c.relation], *_lane_order(c.priority, c.scores.pr_merged, c.updated_at)),
    )
    needs_you = sorted(
        (c for c in kept if c.priority != "P0" and c.relation == BriefingReportRelation.WAITING_FOR_YOU),
        key=lambda c: _lane_order(c.priority, c.scores.action, c.updated_at),
    )
    to_ship = sorted(
        (c for c in kept if c.priority != "P0" and c.relation != BriefingReportRelation.WAITING_FOR_YOU),
        key=lambda c: _lane_order(c.priority, c.scores.pr_merged, c.updated_at),
    )
    if limit is None:
        return urgent + needs_you + to_ship
    free = max(limit - len(urgent), 0)
    to_ship_slots = min(len(to_ship), free - math.ceil(free * NEEDS_YOU_SHARE))
    needs_you_slots = min(len(needs_you), free - to_ship_slots)
    to_ship_slots = min(len(to_ship), free - needs_you_slots)
    return (urgent + needs_you[:needs_you_slots] + to_ship[:to_ship_slots])[:limit]


def reports_for_briefing(*, team_id: int, user_id: int, limit: int | None = None) -> list[BriefingReport]:
    """Open, actionable reports for one person, in briefing order, each tagged with its strongest relation.

    A report appears once, under the first `BriefingReportRelation` that matches. Every open report
    of a relation is a candidate, up to `_CANDIDATES_PER_RELATION`, so the model ranks the whole
    set and not only the newest reports. Urgent-unowned keeps only P0. `_briefing_pick` orders the
    candidates and `limit` keeps the best of them.
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
    relations: dict[str, BriefingReportRelation] = {}
    updated: dict[str, datetime] = {}
    for relation, condition in buckets:
        rows = (
            open_reports.filter(condition)
            .order_by("-updated_at")
            .values_list("id", "updated_at")[:_CANDIDATES_PER_RELATION]
        )
        for report_id, updated_at in rows:
            key = str(report_id)
            if key not in relations:
                relations[key] = relation
                updated[key] = updated_at
    priorities = _priorities(list(relations))
    eligible = [
        report_id
        for report_id, relation in relations.items()
        if relation != BriefingReportRelation.URGENT_UNOWNED or priorities.get(report_id) == "P0"
    ]
    scores = _served_scores(eligible)
    chosen = _briefing_pick(
        [
            _BriefingCandidate(
                report_id=report_id,
                relation=relations[report_id],
                priority=priorities.get(report_id),
                updated_at=updated[report_id],
                scores=scores.get(report_id, _NO_SCORES),
            )
            for report_id in eligible
        ],
        limit,
    )
    chosen_ids = [candidate.report_id for candidate in chosen]
    reports = {str(report.id): report for report in SignalReport.objects.filter(team_id=team_id, id__in=chosen_ids)}
    source_products = _source_products(team_id, chosen_ids)
    with_pr = {
        str(report_id)
        for report_id in SignalReport.objects.filter(team_id=team_id, id__in=chosen_ids)
        .filter(implementation_pr_report_filter(team_id=team_id))
        .values_list("id", flat=True)
    }
    return [
        BriefingReport(
            report_id=candidate.report_id,
            relation=candidate.relation,
            title=_trimmed(report.title, 200) or "Untitled report",
            summary=_trimmed(report.summary, _SUMMARY_LIMIT),
            status=report.status,
            priority=candidate.priority,
            has_implementation_pr=candidate.report_id in with_pr,
            source_products=source_products.get(candidate.report_id, []),
            updated_at=report.updated_at,
            pr_merged_probability=candidate.scores.pr_merged,
        )
        for candidate in chosen
        if (report := reports.get(candidate.report_id)) is not None
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
            "id", "status", "summary", "metrics", "charts", "signal_count", "updated_at"
        )
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
