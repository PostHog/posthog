from dataclasses import dataclass

import structlog
import temporalio
import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Organization
from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.report_generation.select_repo import RepoSelectionResult, select_repository_for_report
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPO_DISCOVERY_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.models import SandboxEnvironment

# Repo discovery only runs `gh` CLI commands — limit egress to GitHub hosts.
GITHUB_ONLY_DOMAINS = [
    "github.com",
    "www.github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "codeload.github.com",
]

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


def _capture_repo_research_event(
    event: str,
    team: Team,
    organization: Organization,
    report_id: str,
    result: str | None = None,
    failure_reason: str | None = None,
) -> None:
    properties: dict = {"report_id": report_id}
    if result is not None:
        properties["result"] = result
    if failure_reason is not None:
        properties["failure_reason"] = failure_reason
    try:
        posthoganalytics.capture(
            event=event,
            distinct_id=str(team.uuid),
            properties=properties,
            groups=groups(organization, team),
        )
    except Exception:
        # Swallow the exception, to avoid breaking the flow over failed analytics event
        logger.exception(
            "Failed to capture repo research event",
            event=event,
            report_id=report_id,
        )


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
    team = await Team.objects.select_related("organization").aget(pk=input.team_id)
    _capture_repo_research_event(
        "signals_repo_research_started",
        team,
        team.organization,
        input.report_id,
    )
    try:
        async with Heartbeater():
            # Check for a previous selection from an earlier run, if any
            previous = await database_sync_to_async(_load_previous_repo_selection, thread_sensitive=False)(
                input.report_id
            )
            if previous is not None and previous.repository is not None:
                logger.info(
                    "signals repo selection reused from previous run",
                    report_id=input.report_id,
                    repository=previous.repository,
                )
                _capture_repo_research_event(
                    "signals_repo_research_completed",
                    team,
                    team.organization,
                    input.report_id,
                    result="reused",
                )
                return previous

            user_id = await database_sync_to_async(_resolve_team_repo_context, thread_sensitive=False)(input.team_id)
            sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
                input.team_id,
                SIGNALS_REPO_DISCOVERY_ENV_NAME,
                SandboxEnvironment.NetworkAccessLevel.CUSTOM,
                allowed_domains=GITHUB_ONLY_DOMAINS,
            )
            result = await select_repository_for_report(
                team_id=input.team_id,
                user_id=user_id,
                signals=input.signals,
                sandbox_environment_id=sandbox_env_id,
            )
            logger.info(
                "signals repo selection completed",
                report_id=input.report_id,
                repository=result.repository,
                reason=result.reason,
            )
            _capture_repo_research_event(
                "signals_repo_research_completed",
                team,
                team.organization,
                input.report_id,
                result="selected" if result.repository is not None else "no_repo",
            )
            return result
    except Exception as e:
        failure_reason = "no_github_integration" if isinstance(e, RuntimeError) else "agentic_activity_error"
        _capture_repo_research_event(
            "signals_repo_research_completed",
            team,
            team.organization,
            input.report_id,
            result="failed",
            failure_reason=failure_reason,
        )
        raise
