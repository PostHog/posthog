import json
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.db import transaction

import structlog
import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.hogql import ast

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.temporal.actionability_judge import (
    ActionabilityChoice,
    ActionabilityJudgeInput,
    actionability_judge_activity,
)
from products.signals.backend.temporal.agentic.report import (
    RunAgenticReportInput,
    RunAgenticReportOutput,
    SignalsLegacyReportGateInput,
    run_agentic_report_activity,
    signals_legacy_report_gate_activity,
)
from products.signals.backend.temporal.agentic.select_repository import (
    SelectRepositoryInput,
    select_repository_activity,
)
from products.signals.backend.temporal.clickhouse import execute_hogql_query_with_retry
from products.signals.backend.temporal.report_safety_judge import SafetyJudgeInput, report_safety_judge_activity
from products.signals.backend.temporal.summarize_signals import (
    SummarizeSignalsInput,
    SummarizeSignalsOutput,
    summarize_signals_activity,
)
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs
from products.signals.backend.utils import EMBEDDING_MODEL

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
    3. If the feature flag is off: use the legacy summarize + safety + actionability flow
    4. If the feature flag is on: run safety first, then the agentic report research flow
    5. Apply the resulting actionability decision to transition the report
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
            return
        # 2. Mark report as in_progress to prevent duplicate runs while this workflow is active
        await workflow.execute_activity(
            mark_report_in_progress_activity,
            MarkReportInProgressInput(
                team_id=inputs.team_id, report_id=inputs.report_id, signal_count=len(fetch_result.signals)
            ),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        try:
            use_legacy_report: bool = await workflow.execute_activity(
                signals_legacy_report_gate_activity,
                SignalsLegacyReportGateInput(team_id=inputs.team_id),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            decision: ReportDecision | None = None
            if not use_legacy_report:
                workflow.logger.info(f"Report {inputs.report_id} using agentic summary path")
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
                    workflow.logger.warning(
                        f"Report {inputs.report_id} failed safety review: {safety_result.explanation}"
                    )
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
                    return
                # 4. Select repository for the agentic research
                repo_result: RepoSelectionResult = await workflow.execute_activity(
                    select_repository_activity,
                    SelectRepositoryInput(
                        team_id=inputs.team_id,
                        report_id=inputs.report_id,
                        signals=fetch_result.signals,
                    ),
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
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
            else:
                # 4. Summarize signals
                summarize_result: SummarizeSignalsOutput = await workflow.execute_activity(
                    summarize_signals_activity,
                    SummarizeSignalsInput(report_id=inputs.report_id, signals=fetch_result.signals),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                safety_result, actionability_result = await asyncio.gather(
                    # 5. Decide if the report is safe to process
                    workflow.execute_activity(
                        report_safety_judge_activity,
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
                    # 6. Judge the report's actionability and priority
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
                    workflow.logger.warning(
                        f"Report {inputs.report_id} failed safety review: {safety_result.explanation}"
                    )
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
                    return
                decision = ReportDecision(
                    title=summarize_result.title,
                    summary=summarize_result.summary,
                    choice=actionability_result.choice,
                    explanation=actionability_result.explanation,
                )
            assert decision is not None
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
                return
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
                return
            await workflow.execute_activity(
                mark_report_ready_activity,
                MarkReportReadyInput(
                    team_id=inputs.team_id,
                    report_id=inputs.report_id,
                    title=decision.title,
                    summary=decision.summary,
                ),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception as e:
            await workflow.execute_activity(
                mark_report_failed_activity,
                MarkReportFailedInput(team_id=inputs.team_id, report_id=inputs.report_id, error=str(e)),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise


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
                timestamp
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
              AND NOT JSONExtractBool(metadata, 'deleted')
            ORDER BY timestamp ASC
        """

        result = await execute_hogql_query_with_retry(
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
            document_id, content, metadata_str, timestamp_raw = row
            # HogQL returns datetime objects, but defend against strings too
            if isinstance(timestamp_raw, str):
                timestamp_raw = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
            if timestamp_raw.tzinfo is None:
                timestamp_raw = timestamp_raw.replace(tzinfo=UTC)
            # Purposefully throw here if we fail - we rely on metadata being correct, and it's not llm generated, so
            # no defensive parsing, we want to fail loudly.
            metadata = json.loads(metadata_str)
            signals.append(
                SignalData(
                    signal_id=document_id,
                    content=content,
                    source_product=metadata.get("source_product", ""),
                    source_type=metadata.get("source_type", ""),
                    source_id=metadata.get("source_id", ""),
                    weight=metadata.get("weight", 0.0),
                    timestamp=timestamp_raw,
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


@temporalio.activity.defn
async def mark_report_ready_activity(input: MarkReportReadyInput) -> None:
    """Mark a report as ready after successful summarization and judge checks."""
    try:

        @transaction.atomic
        def do_update():
            report = SignalReport.objects.select_for_update().get(id=input.report_id, team_id=input.team_id)
            updated_fields = report.transition_to(SignalReport.Status.READY, title=input.title, summary=input.summary)
            report.save(update_fields=updated_fields)

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
