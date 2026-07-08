from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from django.db import transaction

from products.signals.backend.artefact_schemas import ArtefactContent, SuggestedReviewers
from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
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
    registered_artefacts: Sequence[ArtefactContent] = (),
) -> PersistedCustomAgentReport:
    """Create a final READY report plus compatible artefacts in one transaction.

    `agent_identifier` is the agent's `(product, type)` pair; it labels the `task_run` artefact
    when this run produced a task. `registered_artefacts` are typed content models of any
    artefact type, queued during the run via the agent's `register_artefact`, written in queue
    order (status types route through their latest-wins append semantics).
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
            content=repo_selection,
            attribution=attribution,
        )
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=report_id,
            content=final_report.actionability,
            attribution=attribution,
        )
        if final_report.priority is not None:
            SignalReportArtefact.append_status(
                team_id=team_id,
                report_id=report_id,
                content=final_report.priority,
                attribution=attribution,
            )
        if final_report.assignees:
            SignalReportArtefact.append_status(
                team_id=team_id,
                report_id=report_id,
                content=SuggestedReviewers.model_validate(
                    [assignee.model_dump(mode="json") for assignee in final_report.assignees]
                ),
                attribution=attribution,
                reevaluate_autostart=False,
            )

        for artefact_content in registered_artefacts:
            SignalReportArtefact.append(
                team_id=team_id,
                report_id=report_id,
                content=artefact_content,
                attribution=attribution,
                reevaluate_autostart=False,
            )

        if task_id is not None:
            product, type = agent_identifier
            append_task_run_artefact(
                team_id=team_id,
                report_id=str(report.id),
                product=product,
                type=type,
                task_id=task_id,
            )

    return PersistedCustomAgentReport(report_id=str(report.id), task_id=task_id)
