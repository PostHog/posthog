import json
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen
from posthog.models import Team

from products.signals.backend.artefact_schemas import ActionabilityChoice
from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports
from products.signals.backend.models import SignalReport, SignalReportArtefact
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


def _latest_content(report: SignalReport, artefact_type: str) -> dict[str, object]:
    content = (
        report.artefacts.filter(type=artefact_type).order_by("-created_at").values_list("content", flat=True).first()
    )
    try:
        data = json.loads(content or "")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_STARTABLE_STATUSES = frozenset({SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT})


def _can_start_work(report: SignalReport, has_pull_requests: bool) -> bool:
    return (
        report.status in _STARTABLE_STATUSES
        and report.latest_already_addressed is not True
        and report.latest_actionability != ActionabilityChoice.NOT_ACTIONABLE.value
        and not has_pull_requests
    )


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
        for signal in fetch_signals_for_report_sync(team, report_id)
    ]


def report_page_source(*, team: Team, report_id: str) -> ReportPageSource | None:
    team_id = team.id
    report = (
        SignalReport.objects.filter(team_id=team_id, id=report_id)
        .exclude(status=SignalReport.Status.DELETED)
        .only("id", "status", "summary", "suggested_prompts", "latest_actionability", "latest_already_addressed")
        .first()
    )
    if report is None:
        return None
    has_pull_requests = bool(fetch_implementation_prs_for_reports([report_id], team_id=team_id).get(report_id))
    prompts = [prompt for prompt in report.suggested_prompts or [] if isinstance(prompt, str)]
    repository = _latest_content(report, SignalReportArtefact.ArtefactType.REPO_SELECTION).get("repository")
    return ReportPageSource(
        summary=report.summary or "",
        sections=report_sections(report.summary),
        action_prompts=prompts if _can_start_work(report, has_pull_requests) else [],
        repo_slug=repository if isinstance(repository, str) and repository else None,
        signals=_report_signals(team, report_id),
    )
