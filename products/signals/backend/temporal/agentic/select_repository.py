from dataclasses import dataclass

import structlog
import temporalio
import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Organization
from posthog.models.integration import GitHubIntegrationError
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.report_generation.select_repo import (
    RepoSelectionResult,
    resolve_team_github_integration,
    select_repository_for_report,
)
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


def _resolve_sandbox_user_id(team_id: int) -> int | None:
    """Select a user to assign sandbox to."""
    github = resolve_team_github_integration(team_id)
    if github is None:
        return None
    return resolve_user_id_for_team(team_id, github=github)


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
    except Exception as e:
        # Swallow the exception, to avoid breaking the flow over failed analytics event
        posthoganalytics.capture_exception(e)
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
@posthoganalytics.scoped()
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

            user_id = await database_sync_to_async(_resolve_sandbox_user_id, thread_sensitive=False)(input.team_id)
            if user_id is None:
                logger.info(
                    "signals repo selection skipped: No GitHub integration connected to a team/user",
                    report_id=input.report_id,
                    team_id=input.team_id,
                )
                no_repo_result = RepoSelectionResult(
                    repository=None,
                    reason="No GitHub integration connected to a team/user.",
                )
                _capture_repo_research_event(
                    "signals_repo_research_completed",
                    team,
                    team.organization,
                    input.report_id,
                    result="no_repo",
                )
                return no_repo_result
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
        _capture_repo_research_event(
            "signals_repo_research_completed",
            team,
            team.organization,
            input.report_id,
            result="failed",
            failure_reason="agentic_activity_error",
        )
        # Permanent GitHub App auth failures (installation gone/suspended) won't recover via retry.
        if isinstance(e, GitHubIntegrationError) and e.status_code in {401, 403, 404, 410}:
            raise temporalio.exceptions.ApplicationError(
                str(e),
                type="GitHubIntegrationError",
                non_retryable=True,
            ) from e
        raise
