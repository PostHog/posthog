import json
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
from products.signals.backend.temporal.llm import summarize_signals
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs

logger = structlog.get_logger(__name__)

EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536


# ============================================================================
# Activities
# ============================================================================


@dataclass
class FetchSignalsForReportInput:
    team_id: int
    report_id: str


@dataclass
class FetchSignalsForReportOutput:
    signals: list[SignalData]


@temporalio.activity.defn
async def fetch_signals_for_report_activity(input: FetchSignalsForReportInput) -> FetchSignalsForReportOutput:
    """
    Fetch all signals associated with a report from ClickHouse.
    Note: fetches 100 signals at most. This may exceed useful LLM input size - we should consider limiting it in the future.
    """
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
class SummarizeSignalsInput:
    report_id: str
    signals: list[SignalData]


@dataclass
class SummarizeSignalsOutput:
    title: str
    summary: str


@temporalio.activity.defn
async def summarize_signals_activity(input: SummarizeSignalsInput) -> SummarizeSignalsOutput:
    """Summarize signals into a title and summary for the report."""
    try:
        title, summary = await summarize_signals(input.signals)
        logger.debug(
            f"Summarized {len(input.signals)} signals for report {input.report_id}",
            report_id=input.report_id,
            signal_count=len(input.signals),
            title=title,
        )
        return SummarizeSignalsOutput(title=title, summary=summary)
    except Exception as e:
        logger.exception(
            f"Failed to summarize signals for report {input.report_id}: {e}",
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
    """Mark a report as ready after successful summarization."""
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


# ============================================================================
# Workflow
# ============================================================================


@temporalio.workflow.defn(name="signal-report-summary")
class SignalReportSummaryWorkflow:
    """
    Very simple "testing" workflow. The final step here /will/ be to spawn a new
    cloud task in twig, but that infra isn't quite there yet (and even if it was, I'd
    make that a new PR). For now, it just grabs the full signal group, summarizes it,
    and updates the report.

    TODO - one interesting thing we could do here is let the summarising LLM decide
    "no, this isn't actually actionable yet", or even "no, these aren't actually a real
    signal group", and then either reset the report to a `POTENTIAL` status, or even
    delete it and then re-run the signals themselves through the grouping workflow.

    Flow:
    1. Fetch all signals for the report from ClickHouse
    2. Mark report as in_progress
    3. Summarize signals with a single LLM pass
    4. Update report with title/summary and mark as ready (or failed)
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
            # mark the report as failed, and log an error
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
