import json
from collections.abc import Collection
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen
from posthog.models import Team

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
    status: str
    actionability: str | None
    already_addressed: bool | None
    has_pull_requests: bool
    suggested_prompts: list[str]
    repo_slug: str | None
    signals: list[ReportSignal]


@frozen
class ReportArtefactText:
    artefact_id: str
    type: str
    content: str
    created_at: datetime
    written_by_person: bool


def _latest_content(report: SignalReport, artefact_type: str) -> dict[str, object]:
    content = (
        report.artefacts.filter(type=artefact_type).order_by("-created_at").values_list("content", flat=True).first()
    )
    try:
        data = json.loads(content or "")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
        .only("id", "status", "summary", "suggested_prompts")
        .first()
    )
    if report is None:
        return None
    judgment = _latest_content(report, SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT)
    repo_selection = _latest_content(report, SignalReportArtefact.ArtefactType.REPO_SELECTION)
    actionability = judgment.get("actionability")
    already_addressed = judgment.get("already_addressed")
    repository = repo_selection.get("repository")
    return ReportPageSource(
        summary=report.summary or "",
        sections=report_sections(report.summary),
        status=report.status,
        actionability=actionability if isinstance(actionability, str) else None,
        already_addressed=already_addressed if isinstance(already_addressed, bool) else None,
        has_pull_requests=bool(fetch_implementation_prs_for_reports([report_id], team_id=team_id).get(report_id)),
        suggested_prompts=[prompt for prompt in report.suggested_prompts or [] if isinstance(prompt, str)],
        repo_slug=repository if isinstance(repository, str) and repository else None,
        signals=_report_signals(team, report_id),
    )


def report_artefact_texts(*, team: Team, report_id: str, types: Collection[str]) -> list[ReportArtefactText]:
    rows = (
        SignalReportArtefact.objects.filter(team_id=team.id, report_id=report_id, type__in=list(types))
        .order_by("created_at")
        .values_list("id", "type", "content", "created_at", "created_by_id")
    )
    return [
        ReportArtefactText(
            artefact_id=str(artefact_id),
            type=artefact_type,
            content=content,
            created_at=created_at,
            written_by_person=created_by_id is not None,
        )
        for artefact_id, artefact_type, content, created_at, created_by_id in rows
    ]
