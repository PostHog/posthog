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
from products.signals.backend.temporal.types import SignalData, render_signals_to_text
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.logic.repo_selection.agent import (
    apply_stack_path_disambiguation,
    extract_code_paths_from_context,
    score_candidates_by_stack_paths,
    _list_candidate_repos,
)

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
    try:
        async with Heartbeater():
            # Check for a previous selection from an earlier run, if any.
            # Do not blindly reuse: a wrong first pick used to stick across reports (#86091).
            # Re-validate against current signal stack paths; if they disqualify the prior
            # repo, fall through to a fresh selection.
            previous = await aretry_on_db_connection_drop(
                lambda: database_sync_to_async(persisted_repo_selection, thread_sensitive=False)(input.report_id)
            )
            if previous is not None and previous.repository is not None:
                context_text = render_signals_to_text(input.signals)
                stack_paths = extract_code_paths_from_context(context_text)
                if stack_paths:
                    github = await database_sync_to_async(resolve_team_github_integration, thread_sensitive=False)(
                        input.team_id
                    )
                    if github is not None:
                        candidates = await database_sync_to_async(_list_candidate_repos, thread_sensitive=False)(
                            github, input.team_id
                        )
                        path_hits = await database_sync_to_async(
                            score_candidates_by_stack_paths, thread_sensitive=False
                        )(input.team_id, github, candidates, stack_paths)
                        revalidated = apply_stack_path_disambiguation(
                            previous, paths=stack_paths, path_hits=path_hits
                        )
                        if revalidated.repository != previous.repository:
                            logger.info(
                                "signals repo selection discarded stale previous pick",
                                report_id=input.report_id,
                                previous=previous.repository,
                                revalidated=revalidated.repository,
                            )
                            # Fall through to full selection / human input
                        else:
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
                    else:
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
                else:
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
