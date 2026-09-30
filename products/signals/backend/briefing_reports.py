"""Reports that matter to one person, for the Today briefing.

The briefing ranks items across products, so this module only answers "which reports relate to this
person, and how". It does not order across relations; the caller does that.
"""

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from django.db.models import Q

import pydantic
import structlog

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import ActionabilityChoice, RankingScore, priority_from_judgment
from products.signals.backend.implementation_pr import implementation_pr_report_filter
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_claims import reports_with_active_claim
from products.signals.backend.signal_metadata import fetch_source_products_for_reports
from products.signals.backend.suggested_reviewer_index import report_ids_naming_reviewers

logger = structlog.get_logger(__name__)

_OPEN_STATUSES = (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)
_SUMMARY_LIMIT = 300
PR_MERGED_HEAD = "pr_merged"


class BriefingReportRelation(StrEnum):
    CLAIMED = "claimed"
    WAITING_FOR_YOU = "waiting_for_you"
    SUGGESTED_REVIEWER = "suggested_reviewer"
    URGENT_UNOWNED = "urgent_unowned"


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


@frozen
class ReportState:
    report_id: str
    status: str


def _latest_artefacts(report_ids: Sequence[str], artefact_type: str) -> list[tuple[str, str]]:
    """The newest artefact content of one type per report, as `(report_id, content)`."""
    rows = (
        SignalReportArtefact.objects.filter(report_id__in=report_ids, type=artefact_type)
        .order_by("report_id", "-created_at")
        .distinct("report_id")
        .values_list("report_id", "content")
    )
    return [(str(report_id), content) for report_id, content in rows]


def _priorities(report_ids: Sequence[str]) -> dict[str, str]:
    """Latest priority judgment per report, read the same way the inbox serializer reads it."""
    latest: dict[str, str] = {}
    for report_id, content in _latest_artefacts(report_ids, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT):
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
    for report_id, content in _latest_artefacts(report_ids, SignalReportArtefact.ArtefactType.RANKING_SCORE):
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


def reports_for_briefing(*, team_id: int, user_id: int, limit_per_relation: int = 5) -> list[BriefingReport]:
    """Open, actionable reports for one person, each tagged with its strongest relation to them.

    A report appears once, under the first relation that matches in this order: claimed by the
    person, waiting for their input, naming them as a reviewer, then a P0 that nobody owns.
    """
    user = User.objects.get(id=user_id)
    github_login = user.get_github_login()
    open_reports = (
        SignalReport.objects.filter(team_id=team_id, status__in=_OPEN_STATUSES)
        .exclude(latest_actionability=ActionabilityChoice.NOT_ACTIONABLE.value)
        .exclude(latest_already_addressed=True)
    )
    names_me = Q(
        id__in=report_ids_naming_reviewers(
            team_id=team_id,
            user_uuids=[str(user.uuid)],
            github_logins=[github_login.lower()] if github_login else [],
            logins_match_unidentified_only=False,
        )
    )
    claimed = reports_with_active_claim(team_id=team_id, actor=ArtefactAttribution.from_user(user_id))
    unowned = ~reports_with_active_claim(team_id=team_id) & ~implementation_pr_report_filter(
        team_id=team_id, active_only=True
    )
    buckets: list[tuple[BriefingReportRelation, Q]] = [
        (BriefingReportRelation.CLAIMED, claimed),
        (BriefingReportRelation.WAITING_FOR_YOU, names_me & Q(status=SignalReport.Status.PENDING_INPUT)),
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
        for report in open_reports.filter(condition).order_by("-updated_at")[: page * 3]:
            key = str(report.id)
            if key not in seen:
                seen.add(key)
                picked.append((relation, report))
    picked_ids = [str(report.id) for _, report in picked]
    priorities = _priorities(picked_ids)
    merge_chances = _pr_merged_probabilities(picked_ids)
    source_products = _source_products(team_id, picked_ids)
    with_pr = set(
        SignalReport.objects.filter(team_id=team_id, id__in=[report.id for _, report in picked])
        .filter(implementation_pr_report_filter(team_id=team_id))
        .values_list("id", flat=True)
    )
    results: list[BriefingReport] = []
    counts: dict[BriefingReportRelation, int] = {}
    for relation, report in picked:
        priority = priorities.get(str(report.id))
        if relation == BriefingReportRelation.URGENT_UNOWNED and priority != "P0":
            continue
        if counts.get(relation, 0) >= limit_per_relation:
            continue
        counts[relation] = counts.get(relation, 0) + 1
        results.append(
            BriefingReport(
                report_id=str(report.id),
                relation=relation,
                title=" ".join((report.title or "").split())[:200] or "Untitled report",
                summary=" ".join((report.summary or "").split())[:_SUMMARY_LIMIT],
                status=report.status,
                priority=priority,
                has_implementation_pr=report.id in with_pr,
                source_products=source_products.get(str(report.id), []),
                updated_at=report.updated_at,
                pr_merged_probability=merge_chances.get(str(report.id)),
            )
        )
    return results


def reports_for_me_count(*, team_id: int, user_id: int) -> int:
    """How many open, actionable reports name this person, the count the Today footer shows."""
    user = User.objects.get(id=user_id)
    github_login = user.get_github_login()
    return (
        SignalReport.objects.filter(team_id=team_id, status__in=_OPEN_STATUSES)
        .exclude(latest_actionability=ActionabilityChoice.NOT_ACTIONABLE.value)
        .filter(
            id__in=report_ids_naming_reviewers(
                team_id=team_id,
                user_uuids=[str(user.uuid)],
                github_logins=[github_login.lower()] if github_login else [],
                logins_match_unidentified_only=False,
            )
        )
        .count()
    )


def report_states(*, team_id: int, report_ids: Sequence[str]) -> list[ReportState]:
    """Current status of the given reports, so a briefing written earlier can show which are done."""
    if not report_ids:
        return []
    rows = SignalReport.objects.filter(team_id=team_id, id__in=list(report_ids)).values_list("id", "status")
    return [ReportState(report_id=str(report_id), status=status) for report_id, status in rows]
