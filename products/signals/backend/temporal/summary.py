import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

import structlog
import temporalio
from asgiref.sync import sync_to_async
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.actionability_judge import (
    ActionabilityChoice,
    ActionabilityJudgeInput,
    actionability_judge_activity,
)
from products.signals.backend.temporal.safety_judge import SafetyJudgeInput, safety_judge_activity
from products.signals.backend.temporal.summarize_signals import (
    SummarizeSignalsInput,
    SummarizeSignalsOutput,
    summarize_signals_activity,
)
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536


@dataclass
class FetchSignalsForReportInput:
    team_id: int
    report_id: str


@dataclass
class FetchSignalsForReportOutput:
    signals: list[SignalData]


@temporalio.activity.defn
async def fetch_signals_for_report_activity(input: FetchSignalsForReportInput) -> FetchSignalsForReportOutput:
    try:
        team = await Team.objects.aget(pk=input.team_id)

        query = """
            SELECT
                document_id,
                content,
                metadata,
                toString(timestamp) as timestamp
            FROM (
                SELECT
                    document_id,
                    argMax(content, inserted_at) as content,
                    argMax(metadata, inserted_at) as metadata,
                    argMax(timestamp, inserted_at) as timestamp
                FROM document_embeddings
                WHERE model_name = {model_name}
                  AND product = 'signals'
                  AND document_type = 'signal'
                GROUP BY document_id
            )
            Where JSONExtractString(metadata, 'report_id') = {report_id}
            ORDER BY timestamp ASC
        """

        result = await sync_to_async(execute_hogql_query, thread_sensitive=False)(
            query_type="SignalsFetchForReport",
            query=query,
            team=team,
            placeholders={
                "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
                "report_id": ast.Constant(value=input.report_id),
            },
        )

        signals = []
        for row in result.results or []:
            document_id, content, metadata_str, timestamp = row
            # Purposefully throw here if we fail - we rely on metadata being correct, and it's not llm generated, so
            # no defensive parsing, we want to fail loudly.
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str or {}
            signals.append(
                SignalData(
                    signal_id=document_id,
                    content=content,
                    source_product=metadata.get("source_product", ""),
                    source_type=metadata.get("source_type", ""),
                    source_id=metadata.get("source_id", ""),
                    weight=metadata.get("weight", 0.0),
                    timestamp=timestamp,
                    extra=metadata.get("extra", {}),
                )
            )

        logger.debug(
            f"Fetched {len(signals)} signals for report {input.report_id}",
            team_id=input.team_id,
            report_id=input.report_id,
            signal_count=len(signals),
        )
        return FetchSignalsForReportOutput(signals=signals)
    except Exception as e:
        logger.exception(
            f"Failed to fetch signals for report {input.report_id}: {e}",
            team_id=input.team_id,
            report_id=input.report_id,
        )
        raise


@dataclass
class MarkReportInProgressInput:
    report_id: str
    signal_count: int


@temporalio.activity.defn
async def mark_report_in_progress_activity(input: MarkReportInProgressInput) -> None:
    """Mark a report as in_progress and record the signal count snapshot."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id)
            report.status = SignalReport.Status.IN_PROGRESS
            report.last_run_at = timezone.now()
            report.signals_at_run = input.signal_count
            report.save(update_fields=["status", "last_run_at", "signals_at_run", "updated_at"])

        await sync_to_async(do_update, thread_sensitive=False)()
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
    report_id: str
    title: str
    summary: str


@temporalio.activity.defn
async def mark_report_ready_activity(input: MarkReportReadyInput) -> None:
    """Mark a report as ready after successful summarization and judge checks."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id)
            report.status = SignalReport.Status.READY
            report.title = input.title
            report.summary = input.summary
            report.error = None
            report.save(update_fields=["status", "title", "summary", "error", "updated_at"])

        await sync_to_async(do_update, thread_sensitive=False)()
        logger.debug(
            f"Marked report {input.report_id} as ready",
            report_id=input.report_id,
            title=input.title,
        )
    except Exception as e:
        logger.exception(
            f"Failed to mark report {input.report_id} as ready: {e}",
            report_id=input.report_id,
        )
        raise


@dataclass
class MarkReportFailedInput:
    report_id: str
    error: str


@temporalio.activity.defn
async def mark_report_failed_activity(input: MarkReportFailedInput) -> None:
    """Mark a report as failed and store the error message."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id)
            report.status = SignalReport.Status.FAILED
            report.error = input.error
            report.save(update_fields=["status", "error", "updated_at"])

        await sync_to_async(do_update, thread_sensitive=False)()
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
class MarkReportPendingInputInput:
    report_id: str
    title: str
    summary: str
    reason: str


@temporalio.activity.defn
async def mark_report_pending_input_activity(input: MarkReportPendingInputInput) -> None:
    """Mark a report as pending human input, storing the draft title/summary for human review."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id)
            report.status = SignalReport.Status.PENDING_INPUT
            report.title = input.title
            report.summary = input.summary
            report.error = input.reason
            report.save(update_fields=["status", "title", "summary", "error", "updated_at"])

        await sync_to_async(do_update, thread_sensitive=False)()
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
    report_id: str
    reason: str


@temporalio.activity.defn
async def reset_report_to_potential_activity(input: ResetReportToPotentialInput) -> None:
    """Reset a report's weight to 0 and status to potential (e.g. when deemed not actionable)."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id)
            report.status = SignalReport.Status.POTENTIAL
            report.total_weight = 0.0
            report.promoted_at = None
            report.error = input.reason
            report.save(update_fields=["status", "total_weight", "promoted_at", "error", "updated_at"])

        await sync_to_async(do_update, thread_sensitive=False)()
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


@temporalio.workflow.defn(name="signal-report-summary")
class SignalReportSummaryWorkflow:
    """
    Workflow that runs when a signal report is promoted to candidate status.

    Flow:
    1. Fetch all signals for the report from ClickHouse
    2. Mark report as in_progress
    3. Summarize signals into a title + summary via LLM
    4. Safety judge: assess the report for prompt injection / manipulation attempts
       - If unsafe → mark report as failed, stop
    5. Actionability judge: assess whether the report is actionable by a coding agent
       - If not actionable → reset report weight to 0 and status to potential, stop
    6. Mark report as ready with the generated title and summary
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
        fetch_result: FetchSignalsForReportOutput = await workflow.execute_activity(
            fetch_signals_for_report_activity,
            FetchSignalsForReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not fetch_result.signals:
            workflow.logger.error(f"No signals found for report {inputs.report_id}, marking as failed")
            await workflow.execute_activity(
                mark_report_failed_activity,
                MarkReportFailedInput(report_id=inputs.report_id, error="No signals found"),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return

        await workflow.execute_activity(
            mark_report_in_progress_activity,
            MarkReportInProgressInput(report_id=inputs.report_id, signal_count=len(fetch_result.signals)),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        try:
            summarize_result: SummarizeSignalsOutput = await workflow.execute_activity(
                summarize_signals_activity,
                SummarizeSignalsInput(report_id=inputs.report_id, signals=fetch_result.signals),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            safety_result, actionability_result = await asyncio.gather(
                workflow.execute_activity(
                    safety_judge_activity,
                    SafetyJudgeInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        title=summarize_result.title,
                        summary=summarize_result.summary,
                        signals=fetch_result.signals,
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                ),
                workflow.execute_activity(
                    actionability_judge_activity,
                    ActionabilityJudgeInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        title=summarize_result.title,
                        summary=summarize_result.summary,
                        signals=fetch_result.signals,
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                ),
            )

            if not safety_result.safe:
                workflow.logger.warning(f"Report {inputs.report_id} failed safety review: {safety_result.explanation}")
                await workflow.execute_activity(
                    mark_report_failed_activity,
                    MarkReportFailedInput(
                        report_id=inputs.report_id,
                        error=f"Failed safety review: {safety_result.explanation}",
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return

            if actionability_result.choice == ActionabilityChoice.NOT_ACTIONABLE.value:
                workflow.logger.info(
                    f"Report {inputs.report_id} deemed not actionable: {actionability_result.explanation}"
                )
                await workflow.execute_activity(
                    reset_report_to_potential_activity,
                    ResetReportToPotentialInput(
                        report_id=inputs.report_id,
                        reason=f"Not actionable: {actionability_result.explanation}",
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return

            if actionability_result.choice == ActionabilityChoice.REQUIRES_HUMAN_INPUT.value:
                workflow.logger.info(
                    f"Report {inputs.report_id} requires human input: {actionability_result.explanation}"
                )
                await workflow.execute_activity(
                    mark_report_pending_input_activity,
                    MarkReportPendingInputInput(
                        report_id=inputs.report_id,
                        title=summarize_result.title,
                        summary=summarize_result.summary,
                        reason=f"Requires human input: {actionability_result.explanation}",
                    ),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return

            await workflow.execute_activity(
                mark_report_ready_activity,
                MarkReportReadyInput(
                    report_id=inputs.report_id,
                    title=summarize_result.title,
                    summary=summarize_result.summary,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        except Exception as e:
            await workflow.execute_activity(
                mark_report_failed_activity,
                MarkReportFailedInput(report_id=inputs.report_id, error=str(e)),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
