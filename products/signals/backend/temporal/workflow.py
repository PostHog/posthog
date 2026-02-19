import json
import uuid
import asyncio
from datetime import timedelta

import temporalio.workflow
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from django.conf import settings

from posthog.temporal.common.base import PostHogWorkflow

from products.signals.backend.temporal.activities import (
    AssignSignalInput,
    AssignSignalOutput,
    EmitToClickHouseInput,
    FetchSignalsForReportInput,
    FetchSignalsForReportOutput,
    GenerateEmbeddingInput,
    GenerateEmbeddingOutput,
    GenerateSearchQueriesInput,
    LLMMatchSignalInput,
    MarkReportFailedInput,
    MarkReportInProgressInput,
    MarkReportReadyInput,
    RunSignalSemanticSearchInput,
    RunSignalSemanticSearchOutput,
    SummarizeSignalsInput,
    SummarizeSignalsOutput,
    assign_signal_to_report_activity,
    emit_to_clickhouse_activity,
    fetch_signals_for_report_activity,
    generate_search_queries_activity,
    get_embedding_activity,
    llm_match_signal_activity,
    mark_report_failed_activity,
    mark_report_in_progress_activity,
    mark_report_ready_activity,
    run_signal_semantic_search_activity,
    summarize_signals_activity,
)
from products.signals.backend.temporal.types import EmitSignalInputs, SignalResearchWorkflowInputs


# TODO: Not idempotent on source_id - re-running with the same source_id will create duplicate signals.
# Need to check ClickHouse for existing signal before processing.
@temporalio.workflow.defn(name="emit-signal")
class EmitSignalWorkflow(PostHogWorkflow):
    """
    Workflow for processing a new signal.

    Flow:
    1. Generate embedding for signal content
    2. Find nearest signals already assigned to reports
    3. LLM determines if new signal matches an existing report
    4. Create or update report, check for promotion
    5. Emit signal to ClickHouse with correct report_id
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmitSignalInputs:
        loaded = json.loads(inputs[0])
        return EmitSignalInputs(**loaded)

    @staticmethod
    def workflow_id_for(team_id: int, source_product: str, source_type: str, source_id: str) -> str:
        # Prevents the same signal from being processed simultaneously, but does NOT
        # prevent re-running the workflow for the same source_id (see TODO above).
        return f"{team_id}:{source_product}:{source_type}:{source_id}"

    @temporalio.workflow.run
    async def run(self, inputs: EmitSignalInputs) -> str:
        signal_id = str(uuid.uuid4())

        embedding_result, search_queries_result = await asyncio.gather(
            workflow.execute_activity(
                get_embedding_activity,
                GenerateEmbeddingInput(team_id=inputs.team_id, content=inputs.description),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
            workflow.execute_activity(
                generate_search_queries_activity,
                GenerateSearchQueriesInput(
                    description=inputs.description,
                    source_product=inputs.source_product,
                    source_type=inputs.source_type,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
        )

        queries = search_queries_result.queries

        query_embedding_results: list[GenerateEmbeddingOutput] = await asyncio.gather(
            *[
                workflow.execute_activity(
                    get_embedding_activity,
                    GenerateEmbeddingInput(team_id=inputs.team_id, content=query),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                for query in queries
            ]
        )

        query_results: list[RunSignalSemanticSearchOutput] = await asyncio.gather(
            *[
                workflow.execute_activity(
                    run_signal_semantic_search_activity,
                    RunSignalSemanticSearchInput(
                        team_id=inputs.team_id,
                        embedding=emb_result.embedding,
                        limit=10,
                    ),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                for emb_result in query_embedding_results
            ]
        )

        match_result = await workflow.execute_activity(
            llm_match_signal_activity,
            LLMMatchSignalInput(
                description=inputs.description,
                source_product=inputs.source_product,
                source_type=inputs.source_type,
                queries=queries,
                query_results=[r.candidates for r in query_results],
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        assign_result: AssignSignalOutput = await workflow.execute_activity(
            assign_signal_to_report_activity,
            AssignSignalInput(
                team_id=inputs.team_id,
                signal_id=signal_id,
                description=inputs.description,
                weight=inputs.weight,
                source_product=inputs.source_product,
                source_type=inputs.source_type,
                source_id=inputs.source_id,
                extra=inputs.extra,
                embedding=embedding_result.embedding,
                match_result=match_result,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        await workflow.execute_activity(
            emit_to_clickhouse_activity,
            EmitToClickHouseInput(
                team_id=inputs.team_id,
                signal_id=signal_id,
                description=inputs.description,
                source_product=inputs.source_product,
                source_type=inputs.source_type,
                source_id=inputs.source_id,
                weight=inputs.weight,
                extra=inputs.extra,
                report_id=assign_result.report_id,
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # If the report was just promoted to candidate status, kick off research
        if assign_result.promoted:
            await workflow.start_child_workflow(
                SignalResearchWorkflow.run,
                SignalResearchWorkflowInputs(team_id=inputs.team_id, report_id=assign_result.report_id),
                id=SignalResearchWorkflow.workflow_id_for(inputs.team_id, assign_result.report_id),
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                parent_close_policy=ParentClosePolicy.ABANDON,
                execution_timeout=timedelta(minutes=30),
            )

        return signal_id


@temporalio.workflow.defn(name="signal-research")
class SignalResearchWorkflow(PostHogWorkflow):
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
    def parse_inputs(inputs: list[str]) -> SignalResearchWorkflowInputs:
        loaded = json.loads(inputs[0])
        return SignalResearchWorkflowInputs(**loaded)

    @staticmethod
    def workflow_id_for(team_id: int, report_id: str) -> str:
        return f"signals-report:{team_id}:{report_id}"

    @temporalio.workflow.run
    async def run(self, inputs: SignalResearchWorkflowInputs) -> None:
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
