from __future__ import annotations

import json
from dataclasses import dataclass

from django.db import transaction

from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.report_generation.select_repo import RepoSelectionResult


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
) -> PersistedCustomAgentReport:
    """Create a final READY report plus compatible artefacts in one transaction."""
    with transaction.atomic():
        report = SignalReport.objects.create(
            team_id=team_id,
            status=SignalReport.Status.READY,
            title=final_report.title,
            summary=final_report.description,
            signal_count=0,
            total_weight=0.0,
        )

        artefacts: list[SignalReportArtefact] = [
            SignalReportArtefact(
                team_id=team_id,
                report=report,
                type=SignalReportArtefact.ArtefactType.REPO_SELECTION,
                content=repo_selection.model_dump_json(),
            ),
            SignalReportArtefact(
                team_id=team_id,
                report=report,
                type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                content=final_report.actionability.model_dump_json(),
            ),
        ]
        if final_report.priority is not None:
            artefacts.append(
                SignalReportArtefact(
                    team_id=team_id,
                    report=report,
                    type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                    content=final_report.priority.model_dump_json(),
                )
            )
        if final_report.assignees:
            artefacts.append(
                SignalReportArtefact(
                    team_id=team_id,
                    report=report,
                    type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                    content=json.dumps([assignee.model_dump(mode="json") for assignee in final_report.assignees]),
                )
            )
        SignalReportArtefact.objects.bulk_create(artefacts)

        if task_id is not None:
            SignalReportTask.objects.create(
                team_id=team_id,
                report=report,
                task_id=task_id,
                relationship=SignalReportTask.Relationship.RESEARCH,
            )

    return PersistedCustomAgentReport(report_id=str(report.id), task_id=task_id)
