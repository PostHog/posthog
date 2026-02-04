import json
import uuid
from datetime import timedelta

import temporalio.workflow
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.signals.backend.temporal.activities import (
    AssignSignalInput,
    AssignSignalOutput,
    EmitToClickHouseInput,
    GenerateEmbeddingInput,
    GenerateEmbeddingOutput,
    GetNearestSignalsInput,
    GetNearestSignalsOutput,
    LLMMatchSignalInput,
    assign_signal_to_report_activity,
    emit_to_clickhouse_activity,
    get_embedding_activity,
    get_nearest_assigned_signals_activity,
    llm_match_signal_activity,
)
from products.signals.backend.temporal.types import EmitSignalInputs


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

        embedding_result: GenerateEmbeddingOutput = await workflow.execute_activity(
            get_embedding_activity,
            GenerateEmbeddingInput(team_id=inputs.team_id, content=inputs.description),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        nearest_result: GetNearestSignalsOutput = await workflow.execute_activity(
            get_nearest_assigned_signals_activity,
            GetNearestSignalsInput(team_id=inputs.team_id, embedding=embedding_result.embedding, limit=10),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        match_result = await workflow.execute_activity(
            llm_match_signal_activity,
            LLMMatchSignalInput(
                description=inputs.description,
                source_product=inputs.source_product,
                source_type=inputs.source_type,
                candidates=nearest_result.candidates,
            ),
            start_to_close_timeout=timedelta(minutes=2),
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

        return signal_id
