from collections.abc import Collection
from datetime import datetime
from typing import Any

from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.artefact_schemas import ActionabilityChoice
from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports
from products.signals.backend.models import SignalActorKind, SignalReport, SignalReportArtefact
from products.signals.backend.report_sections import ReportSections, report_sections
from products.signals.backend.signal_metadata import fetch_signals_for_report_sync


@frozen
class ReportSignal:
    signal_id: str
    content: str
    source_product: str
    source_type: str
    source_id: str
    timestamp: datetime
    extra: dict[str, Any]


@frozen
class ReportPageSource:
    summary: str
    sections: ReportSections
    action_prompts: list[str]
    repo_slug: str | None
    signals: list[ReportSignal]


@frozen
class ReportArtefactText:
    artefact_id: str
    type: str
    content: str
    created_at: datetime


_STARTABLE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT})


def _can_start_work(report: SignalReport, has_pull_requests: bool) -> bool:
    return (
        report.status in _STARTABLE_STATUSES
        and report.latest_already_addressed is not True
        and report.latest_actionability != ActionabilityChoice.NOT_ACTIONABLE.value
        and not has_pull_requests
    )


PAGE_SIGNAL_LIMIT = 100


def _report_signals(team: Team, report_id: str) -> list[ReportSignal]:
    return [
        ReportSignal(
            signal_id=signal["signal_id"],
            content=signal["content"],
            source_product=signal["source_product"],
            source_type=signal["source_type"],
            source_id=signal["source_id"],
            timestamp=signal["timestamp"],
            extra=signal["extra"] if isinstance(signal["extra"], dict) else {},
        )
        for signal in fetch_signals_for_report_sync(team, report_id, newest=PAGE_SIGNAL_LIMIT)
    ]


def report_page_source(*, team: Team, report_id: str, with_signals: bool = True) -> ReportPageSource | None:
    team_id = team.id
    report = (
        SignalReport.objects.filter(team_id=team_id, id=report_id)
        .exclude(status=SignalReport.Status.DELETED)
        .only("id", "status", "summary", "suggested_prompts", "latest_actionability", "latest_already_addressed")
        .first()
    )
    if report is None:
        return None
    pull_requests = fetch_implementation_prs_for_reports([report_id], team_id=team_id, using="default")
    has_pull_requests = bool(pull_requests.get(report_id))
    prompts = [prompt for prompt in report.suggested_prompts or [] if isinstance(prompt, str)]
    return ReportPageSource(
        summary=report.summary or "",
        sections=report_sections(report.summary),
        action_prompts=prompts if _can_start_work(report, has_pull_requests) else [],
        repo_slug=report.selected_repository(),
        signals=_report_signals(team, report_id) if with_signals else [],
    )


def report_agent_texts(
    *, team: Team, report_id: str, types: Collection[str], per_type: int = 20
) -> list[ReportArtefactText]:
    """The newest artefacts of each type that an agent wrote, oldest first. Notes people wrote are left out."""
    written_by_person = Q(actor_kind=SignalActorKind.USER) | Q(actor_kind__isnull=True, created_by__isnull=False)
    artefacts = SignalReportArtefact.objects.filter(team_id=team.id, report_id=report_id).exclude(written_by_person)
    rows = [
        row
        for artefact_type in types
        for row in artefacts.filter(type=artefact_type)
        .order_by("-created_at")
        .values_list("id", "type", "content", "created_at")[:per_type]
    ]
    return [
        ReportArtefactText(artefact_id=str(artefact_id), type=artefact_type, content=content, created_at=created_at)
        for artefact_id, artefact_type, content, created_at in sorted(rows, key=lambda row: row[3])
    ]
