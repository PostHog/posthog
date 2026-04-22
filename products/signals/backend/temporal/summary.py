import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction

import structlog
import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_SIGNALS_REPORT_COMPLETED
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.agentic.report import (
    RunAgenticReportInput,
    RunAgenticReportOutput,
    run_agentic_report_activity,
)
from products.signals.backend.temporal.agentic.select_repository import (
    SelectRepositoryInput,
    select_repository_activity,
)
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeInput, report_safety_judge_activity
from products.signals.backend.temporal.signal_queries import (
    FetchSignalsForReportInput,
    FetchSignalsForReportOutput,
    fetch_signals_for_report_activity,
)
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs

logger = structlog.get_logger(__name__)


@dataclass
class ReportDecision:
    title: str
    summary: str
    choice: ActionabilityChoice
    explanation: str


@temporalio.workflow.defn(name="signal-report-summary")
class SignalReportSummaryWorkflow:
    """
    Workflow that runs when a signal report is promoted to candidate status.

    Flow:
    1. Fetch all signals for the report from ClickHouse
    2. Mark report as in_progress
    3. Run safety judge to filter unsafe reports
    4. Select a repository for the agentic research
    5. Run the agentic report research flow
    6. Apply the resulting actionability decision to transition the report
    7. If new signals arrived during the run, loop back to step 1
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SignalReportSummaryWorkflowInputs:
        loaded = json.loads(inputs[0])
        return SignalReportSummaryWorkflowInputs(**loaded)

    @staticmethod
    def workflow_id_for(team_id: int, report_id: str) -> str:
        return f"signals-report:{team_id}:{report_id}"

    @temporalio.workflow.run
    async def run(self, inputs: SignalReportSummaryWorkflowInputs) -> None:
        # If new signals arrived after the report was generated - loop back to process them also
        max_iterations = 10  # Basic safety guard
        for _ in range(max_iterations):
            # Loop internally rather than spawning new workflows because summary workflows are
            # fire-and-forget (ParentClosePolicy.ABANDON), so there's no external caller to wait/restart them.
            should_loop = await self._run_once(inputs)
            if not should_loop:
                return
        workflow.logger.warning(f"Report {inputs.report_id} hit max loop iterations ({max_iterations}), exiting")

    async def _run_once(self, inputs: SignalReportSummaryWorkflowInputs) -> bool:
        """Run a single report generation cycle. Returns True if new signals arrived and another cycle is needed."""
        # 1. Fetch signals for the report
        fetch_result: FetchSignalsForReportOutput = await workflow.execute_activity(
            fetch_signals_for_report_activity,
            FetchSignalsForReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not fetch_result.signals:
            workflow.logger.error(f"No signals found for report {inputs.report_id}, marking as failed")
            await workflow.execute_activity(
                mark_report_failed_activity,
                MarkReportFailedInput(team_id=inputs.team_id, report_id=inputs.report_id, error="No signals found"),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            # No loop, as no signals to process
            return False
        signal_count = len(fetch_result.signals)
        # 2. Mark report as in_progress to prevent duplicate runs while this workflow is active
        await workflow.execute_activity(
            mark_report_in_progress_activity,
            MarkReportInProgressInput(team_id=inputs.team_id, report_id=inputs.report_id, signal_count=signal_count),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        try:
            # 3. Run safety judge first to avoid passing unsafe report into the agentic research
            safety_result = await workflow.execute_activity(
                report_safety_judge_activity,
                SafetyJudgeInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    signals=fetch_result.signals,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if not safety_result.safe:
                workflow.logger.warning(f"Report {inputs.report_id} failed safety review: {safety_result.explanation}")
                await workflow.execute_activity(
                    mark_report_failed_activity,
                    MarkReportFailedInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        error=f"Failed safety review: {safety_result.explanation}",
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                # No loop, as report is unsafe
                return False
            # 4. Select repository for the agentic research
            repo_result: RepoSelectionResult = await workflow.execute_activity(
                select_repository_activity,
                SelectRepositoryInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    signals=fetch_result.signals,
                ),
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if repo_result.repository is None:
                workflow.logger.warning(f"Report {inputs.report_id} no repository selected: {repo_result.reason}")
                decision = ReportDecision(
                    title="Repository selection required",
                    summary=f"Could not automatically select a repository: {repo_result.reason}",
                    choice=ActionabilityChoice.REQUIRES_HUMAN_INPUT,
                    explanation=repo_result.reason,
                )
            else:
                # 5. Run the agentic report research flow with the selected repository to use code/MCP data to assess signals
                agentic_result: RunAgenticReportOutput = await workflow.execute_activity(
                    run_agentic_report_activity,
                    RunAgenticReportInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        signals=fetch_result.signals,
                        repo_selection=repo_result,
                    ),
                    start_to_close_timeout=timedelta(hours=4),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                decision = ReportDecision(
                    title=agentic_result.title,
                    summary=agentic_result.summary,
                    choice=agentic_result.choice,
                    explanation=agentic_result.explanation,
                )
            if decision.choice == ActionabilityChoice.NOT_ACTIONABLE:
                workflow.logger.info(f"Report {inputs.report_id} deemed not actionable: {decision.explanation}")
                await workflow.execute_activity(
                    reset_report_to_potential_activity,
                    ResetReportToPotentialInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        reason=f"Not actionable: {decision.explanation}",
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                # No loop, as report is not actionable
                return False
            if decision.choice == ActionabilityChoice.REQUIRES_HUMAN_INPUT:
                workflow.logger.info(f"Report {inputs.report_id} requires human input: {decision.explanation}")
                await workflow.execute_activity(
                    mark_report_pending_input_activity,
                    MarkReportPendingInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        title=decision.title,
                        summary=decision.summary,
                        reason=f"Requires human input: {decision.explanation}",
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                # No loop, human input is required
                return False
            # 6. Mark ready and check if new signals arrived during the run
            has_new_signals: bool = await workflow.execute_activity(
                mark_report_ready_activity,
                MarkReportReadyInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    title=decision.title,
                    summary=decision.summary,
                    processed_signal_count=signal_count,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            # 7. If new signals arrived during the run - loop back to the start
            if has_new_signals:
                workflow.logger.info(f"Report {inputs.report_id} has new signals since run started, looping")
            else:  # Only emit the notification if we're not going to immediately re-run
                await workflow.execute_activity(
                    publish_report_completed_activity,
                    PublishReportCompletedInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        signals=fetch_result.signals,
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            return has_new_signals
        except Exception as e:
            await workflow.execute_activity(
                mark_report_failed_activity,
                MarkReportFailedInput(team_id=inputs.team_id, report_id=inputs.report_id, error=str(e)),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise


@dataclass
class MarkReportInProgressInput:
    team_id: int
    report_id: str
    signal_count: int


@temporalio.activity.defn
async def mark_report_in_progress_activity(input: MarkReportInProgressInput) -> None:
    """Mark a report as in_progress and advance signals_at_run by 3.

    Advancing signals_at_run ensures that if the report is reset to potential after this run,
    it won't immediately re-promote — it must accumulate 3 new signals beyond the current count
    before the promotion gate passes again.
    """
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id, team_id=input.team_id)
            updated_fields = report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=3)
            report.save(update_fields=updated_fields)

        await database_sync_to_async(do_update, thread_sensitive=False)()
        logger.debug(
            f"Marked report {input.report_id} as in_progress",
            report_id=input.report_id,
            signal_count=input.signal_count,
        )
    except Exception as e:
        logger.exception(
            f"Failed to mark report {input.report_id} as in_progress: {e}",
            report_id=input.report_id,
        )
        raise


@dataclass
class MarkReportReadyInput:
    team_id: int
    report_id: str
    title: str
    summary: str
    processed_signal_count: int


@temporalio.activity.defn
async def mark_report_ready_activity(input: MarkReportReadyInput) -> bool:
    """Mark a report as ready. Returns True if new signals arrived during the run."""
    try:

        @transaction.atomic
        def do_update() -> bool:
            report = SignalReport.objects.select_for_update().get(id=input.report_id, team_id=input.team_id)
            updated_fields = report.transition_to(SignalReport.Status.READY, title=input.title, summary=input.summary)
            report.save(update_fields=updated_fields)
            has_new_signals = report.signal_count > input.processed_signal_count
            if has_new_signals:
                # If more signals arrived while the report was being processed, we want to
                # re-promote it back to candidate and loop to also process new signals
                candidate_fields = report.transition_to(SignalReport.Status.CANDIDATE)
                report.save(update_fields=candidate_fields)
            return has_new_signals

        has_new_signals = await database_sync_to_async(do_update, thread_sensitive=False)()
        logger.debug(
            f"Marked report {input.report_id} as ready",
            report_id=input.report_id,
            title=input.title,
            has_new_signals=has_new_signals,
        )
        return has_new_signals
    except Exception as e:
        logger.exception(
            f"Failed to mark report {input.report_id} as ready: {e}",
            report_id=input.report_id,
        )
        raise


@dataclass
class MarkReportFailedInput:
    team_id: int
    report_id: str
    error: str


@temporalio.activity.defn
async def mark_report_failed_activity(input: MarkReportFailedInput) -> None:
    """Mark a report as failed and store the error message."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id, team_id=input.team_id)
            updated_fields = report.transition_to(SignalReport.Status.FAILED, error=input.error)
            report.save(update_fields=updated_fields)

        await database_sync_to_async(do_update, thread_sensitive=False)()
        logger.debug(
            f"Marked report {input.report_id} as failed",
            report_id=input.report_id,
            error=input.error,
        )
    except Exception as e:
        logger.exception(
            f"Failed to mark report {input.report_id} as failed: {e}",
            report_id=input.report_id,
        )
        raise


@dataclass
class MarkReportPendingInput:
    team_id: int
    report_id: str
    title: str
    summary: str
    reason: str


@temporalio.activity.defn
async def mark_report_pending_input_activity(input: MarkReportPendingInput) -> None:
    """Mark a report as pending human input, storing the draft title/summary for human review."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id, team_id=input.team_id)
            updated_fields = report.transition_to(
                SignalReport.Status.PENDING_INPUT, title=input.title, summary=input.summary, error=input.reason
            )
            report.save(update_fields=updated_fields)

        await database_sync_to_async(do_update, thread_sensitive=False)()
        logger.debug(
            f"Marked report {input.report_id} as pending_input",
            report_id=input.report_id,
            reason=input.reason,
        )
    except Exception as e:
        logger.exception(
            f"Failed to mark report {input.report_id} as pending_input: {e}",
            report_id=input.report_id,
        )
        raise


@dataclass
class ResetReportToPotentialInput:
    team_id: int
    report_id: str
    reason: str


@temporalio.activity.defn
async def reset_report_to_potential_activity(input: ResetReportToPotentialInput) -> None:
    """Reset a report's weight to 0 and status to potential (e.g. when deemed not actionable)."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id, team_id=input.team_id)
            updated_fields = report.transition_to(SignalReport.Status.POTENTIAL, reset_weight=True, error=input.reason)
            report.save(update_fields=updated_fields)

        await database_sync_to_async(do_update, thread_sensitive=False)()
        logger.debug(
            f"Reset report {input.report_id} to potential",
            report_id=input.report_id,
            reason=input.reason,
        )
    except Exception as e:
        logger.exception(
            f"Failed to reset report {input.report_id} to potential: {e}",
            report_id=input.report_id,
        )
        raise


@dataclass
class PublishReportCompletedInput:
    team_id: int
    report_id: str
    signals: list[SignalData]


@temporalio.activity.defn
async def publish_report_completed_activity(input: PublishReportCompletedInput) -> None:
    """Publish a message to Kafka when a report is generated or re-generated."""
    try:
        message = {
            "team_id": input.team_id,
            "report_id": input.report_id,
            "signals": [
                {
                    "document_id": signal.signal_id,
                    "timestamp": signal.timestamp.isoformat(),
                    "source_product": signal.source_product,
                    "source_type": signal.source_type,
                    "source_id": signal.source_id,
                    "extra": signal.extra,
                }
                for signal in input.signals
            ],
        }
        producer = get_producer(topic=KAFKA_SIGNALS_REPORT_COMPLETED)
        producer.produce(
            topic=KAFKA_SIGNALS_REPORT_COMPLETED,
            data=message,
            key=input.report_id,
        )
        await asyncio.to_thread(producer.flush)
        logger.debug(
            f"Published report_completed for report {input.report_id}",
            report_id=input.report_id,
            team_id=input.team_id,
            signal_count=len(input.signals),
        )
    except Exception as e:
        logger.exception(
            f"Failed to publish report_completed for report {input.report_id}: {e}",
            report_id=input.report_id,
            team_id=input.team_id,
        )
        raise
