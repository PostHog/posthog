import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
import temporalio
from asgiref.sync import sync_to_async
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast

from posthog.api.embedding_worker import emit_embedding_request
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.api import emit_signal
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.temporal.clickhouse import execute_hogql_query_with_retry
from products.signals.backend.temporal.grouping_v2 import TeamSignalGroupingV2Workflow
from products.signals.backend.temporal.signal_queries import (
    _DEDUPED_SIGNALS_SUBQUERY,
    EMBEDDING_MODEL,
    FetchSignalsForReportInput,
    FetchSignalsForReportOutput,
    WaitForClickHouseInput,
    WaitForClickHouseSignal,
    _ensure_tz_aware,
    fetch_signals_for_report_activity,
    soft_delete_report_signals,
    wait_for_signal_in_clickhouse_activity,
)
from products.signals.backend.temporal.types import (
    SignalData,
    SignalReportReingestionWorkflowInputs,
    TeamSignalReingestionWorkflowInputs,
)

logger = structlog.get_logger(__name__)

TEAM_SIGNAL_REINGESTION_BATCH_SIZE = 50
GROUPING_PAUSE_EXTENSION = timedelta(minutes=10)
GROUPING_PAUSE_REFRESH_THRESHOLD = timedelta(minutes=2)


@dataclass
class SoftDeleteReportSignalsInput:
    team_id: int
    report_id: str


@temporalio.activity.defn
async def soft_delete_report_signals_activity(input: SoftDeleteReportSignalsInput) -> None:
    """Soft-delete all ClickHouse signals for a report by re-emitting with metadata.deleted=True."""
    team = await Team.objects.aget(pk=input.team_id)
    await sync_to_async(soft_delete_report_signals, thread_sensitive=False)(
        report_id=input.report_id,
        team_id=input.team_id,
        team=team,
    )
    logger.info(
        "Soft-deleted signals for report",
        team_id=input.team_id,
        report_id=input.report_id,
    )


@dataclass
class DeleteReportInput:
    team_id: int
    report_id: str


@temporalio.activity.defn
async def delete_report_activity(input: DeleteReportInput) -> None:
    """Transition a report to DELETED status in Postgres. Idempotent — no-ops if already deleted."""

    def do_delete():
        report = SignalReport.objects.get(id=input.report_id, team_id=input.team_id)
        if report.status == SignalReport.Status.DELETED:
            return  # Already deleted
        updated_fields = report.transition_to(SignalReport.Status.DELETED)
        report.save(update_fields=updated_fields)

    await database_sync_to_async(do_delete, thread_sensitive=False)()
    logger.info(
        "Deleted report",
        team_id=input.team_id,
        report_id=input.report_id,
    )


@dataclass
class ReingestSignalsInput:
    team_id: int
    signals: list["SignalData"]


@temporalio.activity.defn
async def reingest_signals_activity(input: ReingestSignalsInput) -> None:
    """Re-emit all signals via emit_signal() through the active Signals pipeline."""
    team = await Team.objects.aget(pk=input.team_id)

    for signal in input.signals:
        await emit_signal(
            team=team,
            source_product=signal.source_product,
            source_type=signal.source_type,
            source_id=signal.source_id,
            description=signal.content,
            weight=signal.weight,
            extra=signal.extra,
        )

    logger.info(
        "Re-ingested signals via emit_signal",
        team_id=input.team_id,
        signal_count=len(input.signals),
    )


@dataclass
class ProcessTeamSignalsBatchInput:
    team_id: int
    delete_only: bool
    limit: int = TEAM_SIGNAL_REINGESTION_BATCH_SIZE


@dataclass
class ProcessTeamSignalsBatchOutput:
    processed_count: int


@dataclass
class PauseGroupingUntilInput:
    team_id: int
    timestamp: datetime


@dataclass
class GetGroupingPausedStateInput:
    team_id: int


@dataclass
class RestoreGroupingPauseInput:
    team_id: int
    paused_until: datetime | None


@dataclass
class DeleteTeamReportsInput:
    team_id: int


@temporalio.activity.defn
async def process_team_signals_batch_activity(input: ProcessTeamSignalsBatchInput) -> ProcessTeamSignalsBatchOutput:
    team = await Team.objects.aget(pk=input.team_id)

    result = await execute_hogql_query_with_retry(
        query_type="SignalsFetchTeamBatchForReingestion",
        query=f"""
            SELECT
                document_id,
                content,
                metadata,
                timestamp
            FROM ({_DEDUPED_SIGNALS_SUBQUERY})
            WHERE NOT JSONExtractBool(metadata, 'deleted')
            ORDER BY timestamp DESC, document_id DESC
            LIMIT {{limit}}
        """,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "limit": ast.Constant(value=input.limit),
        },
    )

    signals: list[SignalData] = []
    for row in result.results or []:
        document_id, content, metadata_str, timestamp_raw = row
        metadata = json.loads(metadata_str)
        signals.append(
            SignalData(
                signal_id=document_id,
                content=content,
                source_product=metadata.get("source_product", ""),
                source_type=metadata.get("source_type", ""),
                source_id=metadata.get("source_id", ""),
                weight=metadata.get("weight", 0.0),
                timestamp=_ensure_tz_aware(timestamp_raw),
                extra=metadata.get("extra", {}),
                metadata=dict(metadata),
            )
        )

    if not signals:
        logger.info(
            "No team signals left to process",
            team_id=input.team_id,
            delete_only=input.delete_only,
        )
        return ProcessTeamSignalsBatchOutput(processed_count=0)

    for signal in signals:
        temporalio.activity.heartbeat()
        metadata = dict(signal.metadata)
        metadata["deleted"] = True

        await sync_to_async(emit_embedding_request, thread_sensitive=False)(
            content=signal.content,
            team_id=input.team_id,
            product="signals",
            document_type="signal",
            rendering="plain",
            document_id=signal.signal_id,
            models=[m.value for m in EmbeddingModelName],
            timestamp=signal.timestamp,
            metadata=metadata,
        )

        if not input.delete_only:
            await emit_signal(
                team=team,
                source_product=signal.source_product,
                source_type=signal.source_type,
                source_id=signal.source_id,
                description=signal.content,
                weight=signal.weight,
                extra=signal.extra,
            )

    await wait_for_signal_in_clickhouse_activity(
        WaitForClickHouseInput(
            team_id=input.team_id,
            signals=[
                WaitForClickHouseSignal(signal_id=signal.signal_id, timestamp=signal.timestamp) for signal in signals
            ],
            max_wait_time_seconds=3600,
        )
    )

    logger.info(
        "Processed team signals batch",
        team_id=input.team_id,
        delete_only=input.delete_only,
        signal_count=len(signals),
    )
    return ProcessTeamSignalsBatchOutput(processed_count=len(signals))


@temporalio.activity.defn
async def pause_grouping_until_activity(input: PauseGroupingUntilInput) -> None:
    await TeamSignalGroupingV2Workflow.pause_until(input.team_id, input.timestamp)
    logger.info(
        "Paused grouping workflow",
        team_id=input.team_id,
        paused_until=input.timestamp.isoformat(),
    )


@temporalio.activity.defn
async def get_grouping_paused_state_activity(input: GetGroupingPausedStateInput) -> datetime | None:
    return await TeamSignalGroupingV2Workflow.paused_state(input.team_id)


@temporalio.activity.defn
async def restore_grouping_pause_activity(input: RestoreGroupingPauseInput) -> None:
    if input.paused_until is not None and input.paused_until > datetime.now(tz=UTC):
        await TeamSignalGroupingV2Workflow.pause_until(input.team_id, input.paused_until)
        logger.info(
            "Restored grouping pause",
            team_id=input.team_id,
            paused_until=input.paused_until.isoformat(),
        )
        return

    await TeamSignalGroupingV2Workflow.unpause(input.team_id)
    logger.info("Cleared grouping pause", team_id=input.team_id)


@temporalio.activity.defn
async def delete_team_reports_activity(input: DeleteTeamReportsInput) -> None:
    def do_delete() -> tuple[int, int]:
        artefact_count = SignalReportArtefact.objects.filter(team_id=input.team_id).count()
        report_count = SignalReport.objects.filter(team_id=input.team_id).count()

        SignalReportArtefact.objects.filter(team_id=input.team_id).delete()
        SignalReport.objects.filter(team_id=input.team_id).delete()

        return artefact_count, report_count

    artefact_count, report_count = await database_sync_to_async(do_delete, thread_sensitive=False)()
    logger.info(
        "Deleted team signal reports and artefacts",
        team_id=input.team_id,
        artefact_count=artefact_count,
        report_count=report_count,
    )


@temporalio.workflow.defn(name="signal-report-reingestion")
class SignalReportReingestionWorkflow:
    """Delete a report, soft-delete its signals, then re-emit them through the active Signals pipeline."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SignalReportReingestionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return SignalReportReingestionWorkflowInputs(**loaded)

    @staticmethod
    def workflow_id_for(team_id: int, report_id: str) -> str:
        return f"signal-report-reingestion-{team_id}-{report_id}"

    @temporalio.workflow.run
    async def run(self, inputs: SignalReportReingestionWorkflowInputs) -> None:
        # Bind team_id + report_id so all logs flow to the log_entries sink (the Temporal
        # structlog renderer skips producing when team_id isn't in the event dict).
        log = logger.bind(team_id=inputs.team_id, report_id=inputs.report_id)
        # 1. Fetch all signals for the report from ClickHouse
        fetch_result: FetchSignalsForReportOutput = await workflow.execute_activity(
            fetch_signals_for_report_activity,
            FetchSignalsForReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not fetch_result.signals:
            log.warning("No signals found for report, deleting report only")
            await workflow.execute_activity(
                delete_report_activity,
                DeleteReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return

        log.info(
            "Fetched signals for report, proceeding with reingestion",
            signal_count=len(fetch_result.signals),
        )

        # 2. Soft-delete all signals in ClickHouse
        await workflow.execute_activity(
            soft_delete_report_signals_activity,
            SoftDeleteReportSignalsInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 2b. Wait for all soft-deleted signals to land in ClickHouse before re-ingesting
        await workflow.execute_activity(
            wait_for_signal_in_clickhouse_activity,
            WaitForClickHouseInput(
                team_id=inputs.team_id,
                signals=[
                    WaitForClickHouseSignal(
                        signal_id=s.signal_id,
                        timestamp=s.timestamp,
                    )
                    for s in fetch_result.signals
                ],
                max_wait_time_seconds=3600,
            ),
            start_to_close_timeout=timedelta(hours=1, minutes=5),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # 3. Delete the report in Postgres
        await workflow.execute_activity(
            delete_report_activity,
            DeleteReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 4. Re-ingest all signals
        await workflow.execute_activity(
            reingest_signals_activity,
            ReingestSignalsInput(team_id=inputs.team_id, signals=fetch_result.signals),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        log.info(
            "Reingestion complete for report: signals re-submitted to grouping",
            signal_count=len(fetch_result.signals),
        )


@temporalio.workflow.defn(name="team-signal-reingestion")
class TeamSignalReingestionWorkflow:
    """Soft-delete every non-deleted signal for a team, optionally re-queue them, then restore grouping state."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TeamSignalReingestionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return TeamSignalReingestionWorkflowInputs(**loaded)

    @staticmethod
    def workflow_id_for(team_id: int) -> str:
        return f"team-signal-reingestion-{team_id}"

    async def _ensure_grouping_paused(
        self,
        team_id: int,
        original_paused_until: datetime | None,
    ) -> None:
        target_paused_until = workflow.now() + GROUPING_PAUSE_EXTENSION
        if original_paused_until is not None and original_paused_until > target_paused_until:
            target_paused_until = original_paused_until

        await workflow.execute_activity(
            pause_grouping_until_activity,
            PauseGroupingUntilInput(team_id=team_id, timestamp=target_paused_until),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _refresh_grouping_pause_if_needed(
        self,
        team_id: int,
        original_paused_until: datetime | None,
    ) -> None:
        refreshed_paused_until: datetime | None = await workflow.execute_activity(
            get_grouping_paused_state_activity,
            GetGroupingPausedStateInput(team_id=team_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if refreshed_paused_until is None or refreshed_paused_until <= (
            workflow.now() + GROUPING_PAUSE_REFRESH_THRESHOLD
        ):
            await self._ensure_grouping_paused(team_id, original_paused_until)

    @temporalio.workflow.run
    async def run(self, inputs: TeamSignalReingestionWorkflowInputs) -> None:
        original_paused_until: datetime | None = await workflow.execute_activity(
            get_grouping_paused_state_activity,
            GetGroupingPausedStateInput(team_id=inputs.team_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        await self._ensure_grouping_paused(inputs.team_id, original_paused_until)

        try:
            while True:
                await self._refresh_grouping_pause_if_needed(inputs.team_id, original_paused_until)

                batch_result: ProcessTeamSignalsBatchOutput = await workflow.execute_activity(
                    process_team_signals_batch_activity,
                    ProcessTeamSignalsBatchInput(
                        team_id=inputs.team_id,
                        delete_only=inputs.delete_only,
                        limit=TEAM_SIGNAL_REINGESTION_BATCH_SIZE,
                    ),
                    start_to_close_timeout=timedelta(hours=1, minutes=15),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

                if batch_result.processed_count == 0:
                    logger.info(
                        "Team-wide signal reingestion complete",
                        team_id=inputs.team_id,
                        delete_only=inputs.delete_only,
                    )
                    await workflow.execute_activity(
                        delete_team_reports_activity,
                        DeleteTeamReportsInput(team_id=inputs.team_id),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    break
        finally:
            await workflow.execute_activity(
                restore_grouping_pause_activity,
                RestoreGroupingPauseInput(team_id=inputs.team_id, paused_until=original_paused_until),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
