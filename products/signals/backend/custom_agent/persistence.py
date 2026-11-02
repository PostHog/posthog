from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from posthog.models.team.team import Team

from products.signals.backend.artefact_schemas import (
    ArtefactContent,
    ReviewerProposal,
    ReviewerState,
    SuggestedReviewers,
)
from products.signals.backend.custom_agent.schemas import CustomAgentFinalReport
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.reviewer_telemetry import capture_suggested_reviewers_resolved
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.reviewer_rules import ReviewerRules
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
    report_id = str(uuid4())
    assignment = ReviewerRules(team=Team.objects.get(id=team_id), report_id=report_id)
    with transaction.atomic():
        report = SignalReport.objects.create(
            id=report_id,
            team_id=team_id,
            status=SignalReport.Status.READY,
            title=final_report.title,
            summary=final_report.description,
            signal_count=0,
            total_weight=0.0,
            # Born directly READY without passing through transition_to (which stamps this for
            # pipeline reports), so the daily report limit counts it from creation.
            first_visible_at=timezone.now(),
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
        reviewers = (
            SuggestedReviewers.model_validate([assignee.model_dump(mode="json") for assignee in final_report.assignees])
            if final_report.assignees
            else None
        )
        for artefact_content in registered_artefacts:
            if isinstance(artefact_content, SuggestedReviewers):
                reviewers = artefact_content
                continue
            SignalReportArtefact.append(
                team_id=team_id,
                report_id=report_id,
                content=artefact_content,
                attribution=attribution,
                reevaluate_autostart=False,
            )
        if reviewers is not None or assignment.enabled:
            reviewers = reviewers or SuggestedReviewers(root=[])
            artefact = SignalReportArtefact.append_status(
                team_id=team_id,
                report_id=report_id,
                content=reviewers,
                attribution=attribution,
                reviewer_proposal=ReviewerProposal(expected_state=ReviewerState(), source="custom_agent"),
                reevaluate_autostart=False,
            )
            reviewers = SuggestedReviewers.model_validate_json(artefact.content)

        if task_id is not None:
            product, type = agent_identifier
            append_task_run_artefact(
                team_id=team_id,
                report_id=str(report.id),
                product=product,
                type=type,
                task_id=task_id,
            )

    if reviewers is not None:
        capture_suggested_reviewers_resolved(
            team_id=team_id,
            report_id=str(report.id),
            github_logins=[entry.github_login for entry in reviewers.root if entry.github_login],
            user_uuids=[entry.user_uuid for entry in reviewers.root if entry.user_uuid and not entry.github_login],
            source="custom_agent",
        )

    return PersistedCustomAgentReport(report_id=str(report.id), task_id=task_id)
