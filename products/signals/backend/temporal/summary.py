import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

import structlog
import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.actionability_judge import (
    ActionabilityChoice,
    ActionabilityJudgeInput,
    actionability_judge_activity,
)
from products.signals.backend.temporal.coherence_judge import (
    CoherenceJudgeInput,
    CoherenceJudgeOutput,
    coherence_judge_activity,
)
from products.signals.backend.temporal.reassignment import (
    ClassifySignalsInput,
    ClassifySignalsOutput,
    SaveReassignmentInput,
    SaveReassignmentOutput,
    classify_signals_activity,
    save_reassignment_activity,
)
from products.signals.backend.temporal.safety_judge import SafetyJudgeInput, safety_judge_activity
from products.signals.backend.temporal.types import WEIGHT_THRESHOLD, SignalData, SignalReportSummaryWorkflowInputs

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536


@dataclass
class FetchSignalsForReportInput:
    team_id: int
    report_id: str


@dataclass
class FetchSignalsForReportOutput:
    signals: list[SignalData]


FETCH_SIGNALS_MAX_RETRIES = 3
FETCH_SIGNALS_RETRY_DELAY_SECONDS = 30


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
            WHERE JSONExtractString(metadata, 'report_id') = {report_id}
            ORDER BY timestamp ASC
        """

        placeholders = {
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "report_id": ast.Constant(value=input.report_id),
        }

        # Signals are written to ClickHouse via Kafka, so there's an ingestion delay.
        # After report splitting, the re-emitted signals may not be queryable yet.
        # Retry with a delay to handle this eventual consistency.
        for attempt in range(FETCH_SIGNALS_MAX_RETRIES):
            result = await database_sync_to_async(execute_hogql_query, thread_sensitive=False)(
                query_type="SignalsFetchForReport",
                query=query,
                team=team,
                placeholders=placeholders,
            )

            signals = []
            for row in result.results or []:
                document_id, content, metadata_str, timestamp = row
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

            if signals:
                break

            if attempt < FETCH_SIGNALS_MAX_RETRIES - 1:
                logger.warning(
                    f"No signals found for report {input.report_id} on attempt {attempt + 1}, "
                    f"retrying in {FETCH_SIGNALS_RETRY_DELAY_SECONDS}s",
                    report_id=input.report_id,
                    team_id=input.team_id,
                    attempt=attempt + 1,
                )
                await asyncio.sleep(FETCH_SIGNALS_RETRY_DELAY_SECONDS)

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

        await database_sync_to_async(do_update, thread_sensitive=False)()
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
            report = SignalReport.objects.select_for_update().get(id=input.report_id)
            report.status = SignalReport.Status.PENDING_INPUT
            report.title = input.title
            report.summary = input.summary
            report.error = input.reason
            report.save(update_fields=["status", "title", "summary", "error", "updated_at"])

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


@temporalio.workflow.defn(name="signal-report-summary")
class SignalReportSummaryWorkflow:
    """
    Workflow that runs when a signal report is promoted to candidate status.

    Flow:
    1. Fetch all signals for the report from ClickHouse
    2. Mark report as in_progress
    3. Coherence judge: analyze signals, produce title + summary for each distinct topic
       - If 1 report returned → signals are coherent, use title/summary, continue
       - If 2+ reports returned → incoherent, split:
         a. LLM-classify each signal into a report bucket (parallel)
         b. Create new reports, re-emit signals to ClickHouse, mark original as failed
         c. Run child summary workflows for each new report (parallel), stop
    4. Safety judge + Actionability judge — run concurrently:
       - If unsafe → mark report as failed, stop
       - If not actionable → reset report weight to 0 and status to potential, stop
       - If requires human input → mark report as pending_input, stop
    5. Mark report as ready with the generated title and summary
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SignalReportSummaryWorkflowInputs:
        loaded = json.loads(inputs[0])
        return SignalReportSummaryWorkflowInputs(**loaded)

    @staticmethod
    def workflow_id_for(team_id: int, report_id: str) -> str:
        return f"signals-report:{team_id}:{report_id}"

    async def _split_incoherent_report(
        self,
        inputs: SignalReportSummaryWorkflowInputs,
        signals: list[SignalData],
        coherence_result: CoherenceJudgeOutput,
    ) -> None:
        workflow.logger.info(
            f"Report {inputs.report_id} is incoherent, splitting into {len(coherence_result.reports)} reports"
        )

        classify_result: ClassifySignalsOutput = await workflow.execute_activity(
            classify_signals_activity,
            ClassifySignalsInput(
                team_id=inputs.team_id,
                signals=signals,
                new_reports=coherence_result.reports,
            ),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        save_result: SaveReassignmentOutput = await workflow.execute_activity(
            save_reassignment_activity,
            SaveReassignmentInput(
                team_id=inputs.team_id,
                original_report_id=inputs.report_id,
                signals=signals,
                new_reports=coherence_result.reports,
                assignments=classify_result.assignments,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        promoted = [r for r in save_result.created_reports if r.total_weight >= WEIGHT_THRESHOLD]

        if promoted:
            await asyncio.gather(
                *(
                    workflow.execute_child_workflow(
                        SignalReportSummaryWorkflow.run,
                        SignalReportSummaryWorkflowInputs(
                            team_id=inputs.team_id,
                            report_id=created_report.report_id,
                        ),
                        id=SignalReportSummaryWorkflow.workflow_id_for(inputs.team_id, created_report.report_id),
                        execution_timeout=timedelta(hours=1),
                    )
                    for created_report in promoted
                )
            )

    async def _process_report(self, inputs: SignalReportSummaryWorkflowInputs, signals: list[SignalData]) -> None:
        # Coherence judge pulls double duty: summarizes if coherent, splits if not
        coherence_result: CoherenceJudgeOutput = await workflow.execute_activity(
            coherence_judge_activity,
            CoherenceJudgeInput(
                team_id=inputs.team_id,
                report_id=inputs.report_id,
                signals=signals,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if len(coherence_result.reports) > 1:
            await self._split_incoherent_report(inputs, signals, coherence_result)
            return

        # Single coherent report — use the title/summary from the coherence judge
        title = coherence_result.reports[0].title
        summary = coherence_result.reports[0].summary

        safety_result, actionability_result = await asyncio.gather(
            workflow.execute_activity(
                safety_judge_activity,
                SafetyJudgeInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    title=title,
                    summary=summary,
                    signals=signals,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
            workflow.execute_activity(
                actionability_judge_activity,
                ActionabilityJudgeInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    title=title,
                    summary=summary,
                    signals=signals,
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
            workflow.logger.info(f"Report {inputs.report_id} deemed not actionable: {actionability_result.explanation}")
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
            workflow.logger.info(f"Report {inputs.report_id} requires human input: {actionability_result.explanation}")
            await workflow.execute_activity(
                mark_report_pending_input_activity,
                MarkReportPendingInput(
                    report_id=inputs.report_id,
                    title=title,
                    summary=summary,
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
                title=title,
                summary=summary,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    @temporalio.workflow.run
    async def run(self, inputs: SignalReportSummaryWorkflowInputs) -> None:
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
            await self._process_report(inputs, fetch_result.signals)
        except Exception as e:
            await workflow.execute_activity(
                mark_report_failed_activity,
                MarkReportFailedInput(report_id=inputs.report_id, error=str(e)),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
