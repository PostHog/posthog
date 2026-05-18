from __future__ import annotations

from datetime import timedelta

import structlog
import posthoganalytics
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal

from products.signals.backend.auto_start import ReviewerContent, maybe_autostart_implementation_task
from products.signals.backend.custom_agent.loader import import_agent_class, validate_agent_class_identity
from products.signals.backend.custom_agent.persistence import create_custom_agent_ready_report
from products.signals.backend.custom_agent.repo_selection import (
    ResolvedCustomAgentRepository,
    resolve_custom_agent_repository,
)
from products.signals.backend.custom_agent.schemas import (
    CustomAgentFinalReport,
    CustomAgentWorkflowInput,
    CustomAgentWorkflowOutput,
)
from products.signals.backend.models import SignalReport
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)
from products.signals.backend.temporal.agentic import (
    SIGNALS_REPO_DISCOVERY_ENV_NAME,
    get_or_create_signals_sandbox_env,
    resolve_user_id_for_team,
)
from products.signals.backend.temporal.agentic.select_repository import GITHUB_ONLY_DOMAINS
from products.tasks.backend.models import SandboxEnvironment

logger = structlog.get_logger(__name__)


@workflow.defn(name="signals-custom-agent")
class CustomSignalAgentWorkflow:
    @staticmethod
    def workflow_id_for(team_id: int, product: str, type_: str, run_id: str) -> str:
        return f"signals-custom-agent:{team_id}:{product}:{type_}-{run_id}"

    @workflow.run
    async def run(self, inputs: CustomAgentWorkflowInput) -> CustomAgentWorkflowOutput:
        return await workflow.execute_activity(
            run_custom_signal_agent_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=85),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


def _repository_selection_required_report(initial_prompt: str) -> CustomAgentFinalReport:
    return CustomAgentFinalReport(
        title="Repository selection required",
        description=(
            "A custom Signals agent was started, but no connected GitHub repository could be confidently selected "
            "for the request. Choose the repository explicitly and rerun the agent.\n\n"
            f"Initial request:\n{initial_prompt}"
        ),
        actionability=ActionabilityAssessment(
            actionability=ActionabilityChoice.REQUIRES_HUMAN_INPUT,
            explanation="The agent needs a human to pick the subject repository before it can do useful code research.",
            already_addressed=False,
        ),
        priority=PriorityAssessment(
            priority=Priority.P2,
            explanation="The request may be actionable, but repository selection must be resolved first.",
        ),
        assignees=[],
    )


@activity.defn
@scoped_temporal()
async def run_custom_signal_agent_activity(inputs: CustomAgentWorkflowInput) -> CustomAgentWorkflowOutput:
    log = logger.bind(
        team_id=inputs.team_id,
        product=inputs.product,
        type=inputs.type,
        run_id=inputs.run_id,
        agent_path=inputs.agent_path,
    )
    try:
        async with Heartbeater():
            agent_class = import_agent_class(inputs.agent_path)
            validate_agent_class_identity(agent_class, inputs.product, inputs.type)

            team = await Team.objects.select_related("organization").aget(pk=inputs.team_id)
            user_id = await database_sync_to_async(resolve_user_id_for_team, thread_sensitive=False)(inputs.team_id)

            repo_selection_env_id: str | None = None
            if inputs.repository is None:
                repo_selection_env_id = await database_sync_to_async(
                    get_or_create_signals_sandbox_env,
                    thread_sensitive=False,
                )(
                    inputs.team_id,
                    SIGNALS_REPO_DISCOVERY_ENV_NAME,
                    SandboxEnvironment.NetworkAccessLevel.CUSTOM,
                    allowed_domains=GITHUB_ONLY_DOMAINS,
                )

            resolved_repo: ResolvedCustomAgentRepository = await resolve_custom_agent_repository(
                team_id=inputs.team_id,
                user_id=user_id,
                initial_prompt=inputs.initial_prompt,
                repository=inputs.repository,
                sandbox_environment_id=repo_selection_env_id,
            )

            if (
                resolved_repo.mode == "selected"
                and resolved_repo.selected_repository is None
                and not agent_class.continue_without_repository
            ):
                persisted = await database_sync_to_async(create_custom_agent_ready_report, thread_sensitive=False)(
                    team_id=inputs.team_id,
                    final_report=_repository_selection_required_report(inputs.initial_prompt),
                    repo_selection=resolved_repo.repo_selection,
                    task_id=None,
                )
                log.info("custom signal agent stopped for repository selection", report_id=persisted.report_id)
                return CustomAgentWorkflowOutput(
                    report_id=persisted.report_id,
                    status=SignalReport.Status.READY,
                    repository=None,
                    task_id=None,
                )

            agent = agent_class(
                team=team,
                initial_prompt=inputs.initial_prompt,
                repository=resolved_repo.selected_repository,
                run_id=inputs.run_id,
                user_id=user_id,
                model=inputs.model,
            )
            final_report = await agent.start()
            task_id = str(agent.task.id) if agent.task is not None else None
            persisted = await database_sync_to_async(create_custom_agent_ready_report, thread_sensitive=False)(
                team_id=inputs.team_id,
                final_report=final_report,
                repo_selection=resolved_repo.repo_selection,
                task_id=task_id,
            )
            log.info(
                "custom signal agent completed",
                report_id=persisted.report_id,
                repository=resolved_repo.selected_repository,
                task_id=task_id,
            )

            if resolved_repo.selected_repository is not None:
                reviewers_content: list[ReviewerContent] = [
                    ReviewerContent(
                        github_login=assignee.github_login,
                        github_name=assignee.github_name,
                        relevant_commits=list(assignee.relevant_commits),
                    )
                    for assignee in final_report.assignees
                ]
                try:
                    await maybe_autostart_implementation_task(
                        team_id=inputs.team_id,
                        report_id=persisted.report_id,
                        repository=resolved_repo.selected_repository,
                        title=final_report.title,
                        summary=final_report.description,
                        actionability=final_report.actionability,
                        priority=final_report.priority,
                        reviewers_content=reviewers_content,
                    )
                except Exception as error:
                    posthoganalytics.capture_exception(error)
                    log.exception(
                        "custom signal agent auto-start task failed",
                        report_id=persisted.report_id,
                        repository=resolved_repo.selected_repository,
                        error=str(error),
                    )

            return CustomAgentWorkflowOutput(
                report_id=persisted.report_id,
                status=SignalReport.Status.READY,
                repository=resolved_repo.selected_repository,
                task_id=task_id,
            )
    except Exception as exc:
        log.exception("custom signal agent failed", error=str(exc))
        raise
