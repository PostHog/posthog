import structlog
import temporalio
import posthoganalytics
from requests import RequestException

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.event_usage import groups
from posthog.integrations import IntegrationManager
from posthog.models import Organization
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import aretry_on_db_connection_drop, close_db_connections

from products.signals.backend.github_optional import ResearchAccessPolicy, team_has_code_access
from products.signals.backend.recurrence import recurrence_rejects_repository
from products.signals.backend.report_generation.select_repo import (
    RepoSelectionResult,
    persisted_repo_selection,
    resolve_team_github_integration,
    select_repository_for_report,
)
from products.signals.backend.report_monitoring_provenance import monitoring_repository_sources
from products.signals.backend.task_profiles import REPO_SELECTION
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPO_DISCOVERY_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.facade.agents import (
    AgentTurnFailed,
    EmptyAgentTurnError,
    RepositoryContextUnavailable,
    SandboxRunFailed,
    TruncatedAgentOutputError,
    TurnPollTimeout,
)
from products.tasks.backend.facade.repo_selection import (
    RepoSelectionUsageLimitError,
    filter_repository_candidates_for_sources,
)
from products.tasks.backend.facade.repo_selection_types import ReportResearchContext

logger = structlog.get_logger(__name__)


@frozen
class SelectRepositoryInput:
    team_id: int
    report_id: str
    signals: list[SignalData]
    signal_id: str | None = None
    github_optional: bool = False


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def github_optional_pilot_activity(team_id: int) -> bool:
    return await database_sync_to_async(ResearchAccessPolicy.enabled, thread_sensitive=False)(team_id)


def _pilot_code_availability(team_id: int) -> ReportResearchContext:
    integrations = IntegrationManager.github.oauth.list(team_id)
    if not integrations:
        return ReportResearchContext(mode="data_only", repository_status="no_integration")
    adapters = [
        GitHubIntegration(item, source="signals_report_research", priority=Priority.NORMAL) for item in integrations
    ]
    if all(
        adapter.integration.repository_cache_updated_at and adapter.integration.repository_cache == []
        for adapter in adapters
    ):
        return ReportResearchContext(mode="data_only", repository_status="no_repositories")
    if not team_has_code_access(team_id):
        return ReportResearchContext(mode="data_only", repository_status="github_unavailable")
    return ReportResearchContext(mode="code", repository_status="available")


def _resolve_sandbox_user_id(team_id: int) -> int | None:
    """Select a user to assign sandbox to."""
    github = resolve_team_github_integration(team_id)
    if github is None:
        return None
    return resolve_user_id_for_team(team_id, github=github)


def _repo_selection_failure_reason(error: Exception, *, agent_started: bool) -> str:
    if isinstance(error, RepoSelectionUsageLimitError):
        return "usage_limit"
    if isinstance(error, TurnPollTimeout):
        return "poll_timeout"
    if isinstance(error, EmptyAgentTurnError):
        return "empty_output"
    if isinstance(error, TruncatedAgentOutputError):
        return "truncated_output"
    if isinstance(error, ValueError) and agent_started:
        return "output_parse_failed"
    if isinstance(error, AgentTurnFailed):
        return "agent_turn_failed"
    if isinstance(error, SandboxRunFailed):
        return "sandbox_failed"
    if isinstance(error, (GitHubIntegrationError, GitHubRateLimitError, EgressBudgetExhausted, RequestException)):
        return "github_unavailable"
    return "agentic_activity_error"


def _repo_research_attempt_properties(result: str | None, error: Exception | None) -> dict[str, object]:
    properties: dict[str, object] = {}
    if temporalio.activity.in_activity():
        info = temporalio.activity.info()
        properties.update(
            workflow_id=info.workflow_id,
            workflow_run_id=info.workflow_run_id,
            activity_id=info.activity_id,
            attempt=info.attempt,
        )
        if result is not None:
            maximum_attempts = info.retry_policy.maximum_attempts if info.retry_policy else 0
            permanent = isinstance(error, GitHubIntegrationError) and error.status_code in {401, 403, 404, 410}
            if result != "failed" or permanent or maximum_attempts:
                properties["is_final_attempt"] = result != "failed" or permanent or info.attempt >= maximum_attempts
    return properties


def _capture_repo_research_event(
    event: str,
    team: Team,
    organization: Organization,
    report_id: str,
    result: str | None = None,
    failure_reason: str | None = None,
    *,
    task_id: str | None = None,
    task_run_id: str | None = None,
    error: Exception | None = None,
) -> None:
    properties: dict[str, object] = {"report_id": report_id, "event_scope": "attempt"}
    properties.update(_repo_research_attempt_properties(result, error))
    if task_id is not None:
        properties["task_id"] = task_id
    if task_run_id is not None:
        properties["task_run_id"] = task_run_id
    if error is not None:
        properties["error_type"] = type(error).__name__
    if isinstance(error, TurnPollTimeout):
        properties.update(error.diagnostics())
    if isinstance(error, AgentTurnFailed):
        properties["agent_error_category"] = error.category
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


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def select_repository_activity(input: SelectRepositoryInput) -> RepoSelectionResult:
    """Select the most relevant repository for a report's signals.

    The early connect-time reads (the team fetch and the previous-selection lookup) go
    through ``aretry_on_db_connection_drop``: the long-lived worker pools connections via
    pgbouncer, so a pool recycle / failover / deploy can leave a stale pooled connection
    that raises ``OperationalError`` on first use. Retrying once on a fresh connection
    keeps a transient blip from escaping as error-tracking noise (Temporal still retries
    the activity if the DB is genuinely degraded).
    """
    team = await aretry_on_db_connection_drop(
        lambda: Team.objects.select_related("organization").aget(pk=input.team_id)
    )
    _capture_repo_research_event(
        "signals_repo_research_started",
        team,
        team.organization,
        input.report_id,
    )
    research_ids: dict[str, str] = {}

    def capture_research_session(task_id: str, run_id: str) -> None:
        research_ids.update(task_id=task_id, task_run_id=run_id)

    try:
        async with Heartbeater():
            sources = await database_sync_to_async(monitoring_repository_sources, thread_sensitive=False)(
                input.team_id, input.signals
            )
            # Check for a previous selection from an earlier run, if any
            previous = await aretry_on_db_connection_drop(
                lambda: database_sync_to_async(persisted_repo_selection, thread_sensitive=False)(input.report_id)
            )
            # Outside the pilot, research resolves its sandbox user from the team's GitHub integration
            # and raises when there is none. A team that disconnected GitHub after the first run must
            # go back through selection, which returns no repository and asks for a selection.
            if (
                previous is not None
                and previous.repository is not None
                and not input.github_optional
                and await database_sync_to_async(resolve_team_github_integration, thread_sensitive=False)(input.team_id)
                is None
            ):
                logger.info(
                    "signals repo selection reuse skipped: no GitHub integration",
                    report_id=input.report_id,
                    team_id=input.team_id,
                    repository=previous.repository,
                )
                previous = None
            if previous is not None and previous.repository is not None and sources is not None:
                allowed = await database_sync_to_async(
                    filter_repository_candidates_for_sources, thread_sensitive=False
                )(input.team_id, [previous.repository], sources.repositories, sources.require_private_destination)
                if previous.repository not in allowed:
                    previous = None
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
                if input.github_optional:
                    previous.research_context = ReportResearchContext(mode="code", repository_status="available")
                return previous

            if input.github_optional:
                availability = await database_sync_to_async(_pilot_code_availability, thread_sensitive=False)(
                    input.team_id
                )
                if availability.mode == "data_only":
                    _capture_repo_research_event(
                        "signals_repo_research_completed",
                        team,
                        team.organization,
                        input.report_id,
                        result="data_only",
                        failure_reason=availability.repository_status,
                    )
                    return RepoSelectionResult(
                        repository=None,
                        reason="Research will use project data without code access.",
                        research_context=availability,
                        autostart_eligible=False,
                    )

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
                input.team_id, SIGNALS_REPO_DISCOVERY_ENV_NAME, REPO_SELECTION
            )
            result = await select_repository_for_report(
                team_id=input.team_id,
                user_id=user_id,
                signals=input.signals,
                signal_report_id=input.report_id,
                spend_signal_id=input.signal_id,
                sandbox_environment_id=sandbox_env_id,
                monitoring_sources=sources,
                on_research_session=capture_research_session,
            )
            # The shared selector takes a sole eligible repository without reading corrections.
            # A recurrence must honor its parent's rejection before spending on research there.
            if result.repository is not None and await database_sync_to_async(
                recurrence_rejects_repository, thread_sensitive=False
            )(team_id=input.team_id, report_id=input.report_id, repository=result.repository):
                result = RepoSelectionResult(
                    repository=None,
                    reason=(
                        "This repository was rejected for the previous report. "
                        "Choose a repository to continue research."
                    ),
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
                task_id=research_ids.get("task_id"),
                task_run_id=research_ids.get("task_run_id"),
            )
            if input.github_optional:
                availability = (
                    await database_sync_to_async(_pilot_code_availability, thread_sensitive=False)(input.team_id)
                    if result.repository is None
                    else ReportResearchContext(mode="code", repository_status="available")
                )
                result.research_context = ReportResearchContext(
                    mode="code" if result.repository else "data_only",
                    repository_status="available"
                    if result.repository
                    else availability.repository_status
                    if availability.mode == "data_only"
                    else "selection_unresolved",
                )
            return result
    except Exception as e:
        if input.github_optional and isinstance(
            e,
            (
                GitHubIntegrationError,
                GitHubRateLimitError,
                EgressBudgetExhausted,
                RequestException,
                RepositoryContextUnavailable,
            ),
        ):
            logger.warning(
                "signals_repository_unavailable_using_project_data",
                team_id=input.team_id,
                report_id=input.report_id,
                error_type=type(e).__name__,
            )
            _capture_repo_research_event(
                "signals_repo_research_completed",
                team,
                team.organization,
                input.report_id,
                result="data_only",
                failure_reason="github_unavailable",
                error=e,
                task_id=research_ids.get("task_id"),
                task_run_id=research_ids.get("task_run_id"),
            )
            return RepoSelectionResult(
                repository=None,
                reason="GitHub is unavailable. Research will use project data.",
                research_context=ReportResearchContext(mode="data_only", repository_status="github_unavailable"),
                autostart_eligible=False,
            )
        _capture_repo_research_event(
            "signals_repo_research_completed",
            team,
            team.organization,
            input.report_id,
            result="failed",
            failure_reason=_repo_selection_failure_reason(e, agent_started=bool(research_ids)),
            error=e,
            task_id=research_ids.get("task_id"),
            task_run_id=research_ids.get("task_run_id"),
        )
        # Permanent GitHub App auth failures (installation gone/suspended) won't recover via retry.
        if isinstance(e, GitHubIntegrationError) and e.status_code in {401, 403, 404, 410}:
            raise temporalio.exceptions.ApplicationError(
                str(e),
                type="GitHubIntegrationError",
                non_retryable=True,
            ) from e
        raise
