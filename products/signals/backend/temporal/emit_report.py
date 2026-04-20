"""Temporal workflow and activities for emit_report: create a fully-formed report with enrichment.

Flow:
1. Create report (potential → candidate → in_progress)
2. Select repository (reuses select_repository_activity with context_text instead of signals)
3. Run enrichment agent to gather commit hashes, code paths, data context
4. Persist artefacts (repo_selection, findings, actionability, priority, suggested_reviewers)
   — which also triggers conditional auto-start of coding tasks
5. Apply the caller-provided actionability decision (ready / pending_input / not_actionable)
6. Publish Kafka report-completed message (for ready reports)
"""

from dataclasses import dataclass
from datetime import timedelta

import structlog
import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    ReportResearchOutput,
    SignalFinding,
)
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.agentic.select_repository import (
    SelectRepositoryInput,
    select_repository_activity,
)
from products.signals.backend.temporal.summary import (
    MarkReportFailedInput,
    MarkReportPendingInput,
    MarkReportReadyInput,
    PublishReportCompletedInput,
    ResetReportToPotentialInput,
    mark_report_failed_activity,
    mark_report_pending_input_activity,
    mark_report_ready_activity,
    publish_report_completed_activity,
    reset_report_to_potential_activity,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CreateEmitReportInput:
    team_id: int
    report_id: str  # Pre-generated UUID from the caller


@dataclass
class EmitReportWorkflowInput:
    team_id: int
    report_id: str  # Pre-generated UUID, used for workflow ID and report row creation
    title: str
    summary: str
    actionability: str  # ActionabilityChoice.value
    actionability_explanation: str
    priority: str  # Priority.value
    priority_explanation: str


@dataclass
class EnrichAndPersistEmitReportInput:
    team_id: int
    report_id: str
    title: str
    summary: str
    repository: str
    repo_reason: str
    actionability: str  # ActionabilityChoice.value
    actionability_explanation: str
    priority: str  # Priority.value
    priority_explanation: str


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


@temporalio.activity.defn
async def create_emit_report_activity(input: CreateEmitReportInput) -> None:
    """Create a SignalReport row and advance it through potential → candidate → in_progress."""
    import uuid

    from django.db import transaction

    from posthog.sync import database_sync_to_async

    from products.signals.backend.models import SignalReport

    def _create() -> None:
        with transaction.atomic():
            report = SignalReport.objects.create(
                id=uuid.UUID(input.report_id),
                team_id=input.team_id,
                status=SignalReport.Status.POTENTIAL,
                signal_count=0,
                total_weight=1.0,
            )
            candidate_fields = report.transition_to(SignalReport.Status.CANDIDATE)
            report.save(update_fields=candidate_fields)
            in_progress_fields = report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=3)
            report.save(update_fields=in_progress_fields)

    await database_sync_to_async(_create, thread_sensitive=False)()
    logger.info("emit_report: created report", report_id=input.report_id, team_id=input.team_id)


@temporalio.activity.defn
async def enrich_and_persist_emit_report_activity(input: EnrichAndPersistEmitReportInput) -> None:
    """Run enrichment agent, build ReportResearchOutput, persist artefacts, and check auto-start."""
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.signals.backend.report_generation.enrichment import run_report_enrichment
    from products.signals.backend.temporal.agentic import (
        SIGNALS_REPORT_RESEARCH_ENV_NAME,
        get_or_create_signals_sandbox_env,
        resolve_user_id_for_team,
    )
    from products.signals.backend.temporal.agentic.report import _persist_agentic_report_artefacts
    from products.tasks.backend.models import SandboxEnvironment
    from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

    async with Heartbeater():
        # 1. Set up sandbox context
        user_id = await database_sync_to_async(resolve_user_id_for_team, thread_sensitive=False)(input.team_id)
        sandbox_env_id = await database_sync_to_async(get_or_create_signals_sandbox_env, thread_sensitive=False)(
            input.team_id, SIGNALS_REPORT_RESEARCH_ENV_NAME, SandboxEnvironment.NetworkAccessLevel.TRUSTED
        )
        context = CustomPromptSandboxContext(
            team_id=input.team_id,
            user_id=user_id,
            repository=input.repository,
            sandbox_environment_id=sandbox_env_id,
            posthog_mcp_scopes="read_only",
        )

        # 2. Run enrichment agent
        enrichment = await run_report_enrichment(
            title=input.title,
            summary=input.summary,
            context=context,
            report_id=input.report_id,
            branch="master",
        )

        # 3. Convert enrichment finding to SignalFinding for the artefact pipeline
        finding = SignalFinding(
            signal_id=f"emit-report-{input.report_id}",
            relevant_code_paths=enrichment.relevant_code_paths,
            relevant_commit_hashes=enrichment.relevant_commit_hashes,
            data_queried=enrichment.data_queried,
            verified=True,  # Enrichment-only — no verification step
        )

        # 4. Build the full ReportResearchOutput with caller-provided judgments
        actionability = ActionabilityAssessment(
            explanation=input.actionability_explanation,
            actionability=ActionabilityChoice(input.actionability),
            already_addressed=False,
        )
        priority = PriorityAssessment(
            explanation=input.priority_explanation,
            priority=Priority(input.priority),
        )
        result = ReportResearchOutput(
            title=input.title,
            summary=input.summary,
            findings=[finding],
            actionability=actionability,
            priority=priority,
        )

        repo_selection = RepoSelectionResult(
            repository=input.repository,
            reason=input.repo_reason,
        )

        # 5. Persist artefacts (also triggers _maybe_autostart_task_for_report)
        await _persist_agentic_report_artefacts(
            input.team_id,
            input.report_id,
            result,
            repo_selection,
        )

    logger.info(
        "emit_report enrichment and artefact persistence completed",
        report_id=input.report_id,
        repository=input.repository,
        code_paths=len(enrichment.relevant_code_paths),
        commit_hashes=len(enrichment.relevant_commit_hashes),
    )


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def _build_repo_selection_context(title: str, summary: str) -> str:
    """Build free-text context for the repo selection agent from report title/summary."""
    return f"**Report title:** {title}\n\n**Report summary:**\n{summary}"


@temporalio.workflow.defn(name="signal-emit-report")
class EmitReportWorkflow:
    """Workflow for emit_report: enrich a caller-provided report and apply standard post-processing.

    Flow:
    1. Create report row (potential → candidate → in_progress)
    2. Select repository from team's GitHub integrations (reuses select_repository_activity)
    3. Run enrichment agent to gather commit hashes and code paths
    4. Persist artefacts + check auto-start
    5. Apply caller-provided actionability decision
    6. Publish Kafka report-completed message (ready reports only)
    """

    @staticmethod
    def workflow_id_for(team_id: int, report_id: str) -> str:
        return f"signal-emit-report:{team_id}:{report_id}"

    @temporalio.workflow.run
    async def run(self, inputs: EmitReportWorkflowInput) -> None:
        try:
            # 1. Create report row
            await workflow.execute_activity(
                create_emit_report_activity,
                CreateEmitReportInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # 2. Select repository (reuse existing activity with context_text)
            repo_result: RepoSelectionResult = await workflow.execute_activity(
                select_repository_activity,
                SelectRepositoryInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    context_text=_build_repo_selection_context(inputs.title, inputs.summary),
                ),
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            if repo_result.repository is None:
                workflow.logger.warning(f"emit_report {inputs.report_id} no repository selected: {repo_result.reason}")
                await workflow.execute_activity(
                    mark_report_pending_input_activity,
                    MarkReportPendingInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        title=inputs.title,
                        summary=inputs.summary,
                        reason=f"Repository selection required: {repo_result.reason}",
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return

            # 3. Enrich + persist artefacts (triggers auto-start check)
            await workflow.execute_activity(
                enrich_and_persist_emit_report_activity,
                EnrichAndPersistEmitReportInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    title=inputs.title,
                    summary=inputs.summary,
                    repository=repo_result.repository,
                    repo_reason=repo_result.reason,
                    actionability=inputs.actionability,
                    actionability_explanation=inputs.actionability_explanation,
                    priority=inputs.priority,
                    priority_explanation=inputs.priority_explanation,
                ),
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            # 4. Apply the caller-provided actionability decision
            choice = ActionabilityChoice(inputs.actionability)

            if choice == ActionabilityChoice.NOT_ACTIONABLE:
                await workflow.execute_activity(
                    reset_report_to_potential_activity,
                    ResetReportToPotentialInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        reason=f"Not actionable: {inputs.actionability_explanation}",
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return

            if choice == ActionabilityChoice.REQUIRES_HUMAN_INPUT:
                await workflow.execute_activity(
                    mark_report_pending_input_activity,
                    MarkReportPendingInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        title=inputs.title,
                        summary=inputs.summary,
                        reason=f"Requires human input: {inputs.actionability_explanation}",
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return

            # IMMEDIATELY_ACTIONABLE → mark ready
            await workflow.execute_activity(
                mark_report_ready_activity,
                MarkReportReadyInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    title=inputs.title,
                    summary=inputs.summary,
                    processed_signal_count=0,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # 5. Publish Kafka completion (no signals attached)
            await workflow.execute_activity(
                publish_report_completed_activity,
                PublishReportCompletedInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    signals=[],
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        except Exception as e:
            workflow.logger.exception(f"EmitReportWorkflow failed for report {inputs.report_id}: {e}")
            try:
                await workflow.execute_activity(
                    mark_report_failed_activity,
                    MarkReportFailedInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        error=str(e),
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                workflow.logger.exception(f"Failed to mark report {inputs.report_id} as failed after workflow error")
            raise
