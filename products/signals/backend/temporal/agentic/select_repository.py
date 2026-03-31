from dataclasses import dataclass

import structlog
import temporalio

from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.report_generation.select_repo import RepoSelectionResult, select_repository_for_report
from products.signals.backend.temporal.agentic import resolve_user_id_for_team
from products.signals.backend.temporal.types import SignalData

logger = structlog.get_logger(__name__)


@dataclass
class SelectRepositoryInput:
    team_id: int
    report_id: str
    signals: list[SignalData]


def _resolve_team_repo_context(team_id: int) -> int:
    """Resolve user context for repository selection, validating GitHub integration exists."""
    team = Team.objects.get(id=team_id)
    github_integration = Integration.objects.filter(team=team, kind="github").first()
    if not github_integration:
        raise RuntimeError(
            f"No GitHub integration found for team {team_id}. "
            "Signals agentic report generation requires a connected GitHub integration."
        )
    return resolve_user_id_for_team(team_id)


def _load_previous_repo_selection(report_id: str) -> RepoSelectionResult | None:
    """Load a previous repo_selection artefact for this report, if one exists."""
    artefact = (
        SignalReportArtefact.objects.filter(
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.REPO_SELECTION,
        )
        .order_by("-created_at")
        .first()
    )
    if artefact is None:
        return None
    return RepoSelectionResult.model_validate_json(artefact.content)


@temporalio.activity.defn
async def select_repository_activity(input: SelectRepositoryInput) -> RepoSelectionResult:
    """Select the most relevant repository for a report's signals."""
    # Check for a previous selection from an earlier run, if any
    previous = await database_sync_to_async(_load_previous_repo_selection, thread_sensitive=False)(input.report_id)
    if previous is not None and previous.repository is not None:
        logger.info(
            "signals repo selection reused from previous run",
            report_id=input.report_id,
            repository=previous.repository,
        )
        return previous

    user_id = await database_sync_to_async(_resolve_team_repo_context, thread_sensitive=False)(input.team_id)
    result = await select_repository_for_report(
        team_id=input.team_id,
        user_id=user_id,
        signals=input.signals,
    )
    logger.info(
        "signals repo selection completed",
        report_id=input.report_id,
        repository=result.repository,
        reason=result.reason,
    )
    return result
