from __future__ import annotations

import json
from dataclasses import dataclass

from django.db import transaction

from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.task_run_artefacts import append_task_run_artefact


@dataclass(frozen=True)
class PersistedCustomAgentReport:
    report_id: str
    task_id: str | None


def create_custom_agent_ready_report(
    *,
    team_id: int,
    final_report: CustomAgentFinalReport,
    repo_selection: RepoSelectionResult,
    task_id: str | None = None,
    agent_identifier: tuple[str, str],
) -> PersistedCustomAgentReport:
    """Create a final READY report plus compatible artefacts in one transaction.

    `agent_identifier` is the agent's `(product, type)` pair; it labels the `task_run` artefact
    when this run produced a task.
    """
    with transaction.atomic():
        report = SignalReport.objects.create(
            team_id=team_id,
            status=SignalReport.Status.READY,
            title=final_report.title,
            summary=final_report.description,
            signal_count=0,
            total_weight=0.0,
        )

        # Written through the model helpers (the single artefact write path). Auto-start is
        # orchestrated explicitly by the caller after persistence, so the suggested_reviewers
        # append opts out of the model's auto-start re-evaluation hook. Everything the agent
        # produced is attributed to its sandbox task; runs that never spawned one (no `send()`
        # call) fall back to system attribution.
        report_id = str(report.id)
        attribution = ArtefactAttribution.from_task(task_id) if task_id is not None else ArtefactAttribution.system()
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.REPO_SELECTION,
            content=repo_selection.model_dump_json(),
            attribution=attribution,
        )
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=final_report.actionability.model_dump_json(),
            attribution=attribution,
        )
        if final_report.priority is not None:
            SignalReportArtefact.append_status(
                team_id=team_id,
                report_id=report_id,
                type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                content=final_report.priority.model_dump_json(),
                attribution=attribution,
            )
        if final_report.assignees:
            SignalReportArtefact.append_status(
                team_id=team_id,
                report_id=report_id,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                content=json.dumps([assignee.model_dump(mode="json") for assignee in final_report.assignees]),
                attribution=attribution,
                reevaluate_autostart=False,
            )

        if task_id is not None:
            SignalReportTask.objects.create(
                team_id=team_id,
                report=report,
                task_id=task_id,
            )
            product, type = agent_identifier
            append_task_run_artefact(
                team_id=team_id,
                report_id=str(report.id),
                product=product,
                type=type,
                task_id=task_id,
            )

    return PersistedCustomAgentReport(report_id=str(report.id), task_id=task_id)
