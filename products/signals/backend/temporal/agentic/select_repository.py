import asyncio
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
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import aretry_on_db_connection_drop, close_db_connections

from products.signals.backend.report_generation.select_repo import (
    RepoSelectionResult,
    persisted_repo_selection,
    resolve_team_github_integration,
    select_repository_for_report,
)
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPO_DISCOVERY_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.facade import api as tasks_facade

# Repo discovery only runs `gh` CLI commands — limit egress to GitHub hosts.
GITHUB_ONLY_DOMAINS = [
    "github.com",
    "www.github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "codeload.github.com",
]

# GitHub App auth failures with these statuses (installation gone/suspended) won't recover via retry.
PERMANENT_GITHUB_STATUS_CODES = {401, 403, 404, 410}

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


def _activity_info() -> temporalio.activity.Info | None:
    """Info of the running activity, or None when the function runs outside an activity context."""
    try:
        return temporalio.activity.info()
    except RuntimeError:
        return None


def _is_last_attempt(info: temporalio.activity.Info | None) -> bool:
    """Tell whether Temporal schedules another attempt after this one.

    The completion event counts jobs, so only the attempt that decides the job must emit it.
    An unlimited retry policy has no last attempt. Report the attempt as the last one and
    accept a duplicate event, because a silent failure metric is worse.
    """
    if info is None:
        return True
    maximum_attempts = info.retry_policy.maximum_attempts if info.retry_policy is not None else 0
    return maximum_attempts <= 0 or info.attempt >= maximum_attempts


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
    info = _activity_info()
    # Captured on every attempt, as before. The team fetch above sits outside the gate below,
    # so an attempt that dies in that fetch would leave a job with no started event at all.
    _capture_repo_research_event(
        "signals_repo_research_started",
        team,
        team.organization,
        input.report_id,
    )
    try:
        async with Heartbeater():
            # Check for a previous selection from an earlier run, if any
            previous = await aretry_on_db_connection_drop(
                lambda: database_sync_to_async(persisted_repo_selection, thread_sensitive=False)(input.report_id)
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
                tasks_facade.SandboxNetworkAccessLevel.CUSTOM,
                allowed_domains=GITHUB_ONLY_DOMAINS,
            )
            result = await select_repository_for_report(
                team_id=input.team_id,
                user_id=user_id,
                signals=input.signals,
                signal_report_id=input.report_id,
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
    except asyncio.CancelledError as e:
        # A start-to-close or heartbeat deadline reaches the activity as a task cancel, which
        # derives from BaseException, so `except Exception` below never sees a timed-out job.
        if _is_last_attempt(info):
            _capture_repo_research_event(
                "signals_repo_research_completed",
                team,
                team.organization,
                input.report_id,
                result="failed",
                failure_reason=type(e).__name__,
            )
        raise
    except Exception as e:
        non_retryable = isinstance(e, GitHubIntegrationError) and e.status_code in PERMANENT_GITHUB_STATUS_CODES
        if non_retryable or _is_last_attempt(info):
            _capture_repo_research_event(
                "signals_repo_research_completed",
                team,
                team.organization,
                input.report_id,
                result="failed",
                failure_reason=type(e).__name__,
            )
        if non_retryable:
            raise temporalio.exceptions.ApplicationError(
                str(e),
                type="GitHubIntegrationError",
                non_retryable=True,
            ) from e
        raise
