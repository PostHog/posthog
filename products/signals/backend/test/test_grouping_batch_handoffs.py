from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest
from unittest.mock import patch

from products.signals.backend.temporal.grouping import (
    AssignAndEmitSignalInput,
    AssignAndEmitSignalOutput,
    FetchReportContextsOutput,
    GenerateEmbeddingInput,
    GenerateEmbeddingOutput,
    GenerateSearchQueriesInput,
    GenerateSearchQueriesOutput,
    MatchSignalToReportInput,
    _process_signal_batch,
    assign_and_emit_signal_activity,
    dispatch_signal_handoffs_activity,
    fetch_report_contexts_activity,
    fetch_signal_type_examples_activity,
    generate_search_queries_activity,
    get_embedding_activity,
    match_signal_to_report_activity,
)
from products.signals.backend.temporal.signal_queries import (
    FetchSignalTypeExamplesInput,
    FetchSignalTypeExamplesOutput,
    RunSignalSemanticSearchInput,
    RunSignalSemanticSearchOutput,
    WaitForClickHouseInput,
    WaitForClickHouseMode,
    run_signal_semantic_search_activity,
    wait_for_signal_in_clickhouse_activity,
)
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    NewReportMatch,
    NoMatchMetadata,
    SignalReportSummaryWorkflowInputs,
)

GROUPING_MODULE_PATH = "products.signals.backend.temporal.grouping"


def _signal(source_id: str) -> EmitSignalInputs:
    return EmitSignalInputs(
        team_id=1,
        source_product="test",
        source_type="signal",
        source_id=source_id,
        description=f"signal {source_id}",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("use_handoffs", "handoff_indices", "expected_wait_indices"),
    [
        (False, set(), [0, 1]),
        (True, {0}, [1]),
        (True, {0, 1}, []),
    ],
)
async def test_batch_waits_only_for_immediately_emitted_signals_before_starting_summary(
    use_handoffs: bool, handoff_indices: set[int], expected_wait_indices: list[int]
) -> None:
    signal_ids = iter((UUID("00000000-0000-0000-0000-000000000001"), UUID("00000000-0000-0000-0000-000000000002")))
    assigned_inputs: list[AssignAndEmitSignalInput] = []
    activity_order: list[str] = []
    wait_inputs: list[WaitForClickHouseInput] = []
    dispatch_inputs: list[SignalReportSummaryWorkflowInputs] = []

    async def execute_activity(activity_fn: Callable[..., object], input: object, **kwargs: object) -> object:
        if activity_fn is fetch_signal_type_examples_activity:
            assert isinstance(input, FetchSignalTypeExamplesInput)
            return FetchSignalTypeExamplesOutput(examples=[])
        if activity_fn is get_embedding_activity:
            assert isinstance(input, GenerateEmbeddingInput)
            return GenerateEmbeddingOutput(embedding=[1.0])
        if activity_fn is generate_search_queries_activity:
            assert isinstance(input, GenerateSearchQueriesInput)
            return GenerateSearchQueriesOutput(queries=["related signal"])
        if activity_fn is run_signal_semantic_search_activity:
            assert isinstance(input, RunSignalSemanticSearchInput)
            return RunSignalSemanticSearchOutput(candidates=[])
        if activity_fn is fetch_report_contexts_activity:
            return FetchReportContextsOutput(contexts={})
        if activity_fn is match_signal_to_report_activity:
            assert isinstance(input, MatchSignalToReportInput)
            return NewReportMatch(
                title="Report",
                summary="Summary",
                match_metadata=NoMatchMetadata(reason="new report"),
            )
        if activity_fn is assign_and_emit_signal_activity:
            assert isinstance(input, AssignAndEmitSignalInput)
            assigned_inputs.append(input)
            return AssignAndEmitSignalOutput(
                report_id="report-1",
                promoted=len(assigned_inputs) == 1,
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                run_count=1,
                signal_key=(f"handoff-{len(assigned_inputs)}" if len(assigned_inputs) - 1 in handoff_indices else None),
            )
        if activity_fn is wait_for_signal_in_clickhouse_activity:
            assert isinstance(input, WaitForClickHouseInput)
            activity_order.append("wait")
            wait_inputs.append(input)
            return None
        if activity_fn is dispatch_signal_handoffs_activity:
            assert isinstance(input, SignalReportSummaryWorkflowInputs)
            activity_order.append("dispatch")
            dispatch_inputs.append(input)
            return None
        raise AssertionError(f"Unexpected activity: {activity_fn}")

    async def start_child_workflow(*args: object, **kwargs: object) -> None:
        activity_order.append("child")

    def patched(patch_id: str) -> bool:
        return use_handoffs if patch_id == "signals-stage-handoffs-v1" else False

    with (
        patch(f"{GROUPING_MODULE_PATH}.workflow.execute_activity", side_effect=execute_activity),
        patch(f"{GROUPING_MODULE_PATH}.workflow.start_child_workflow", side_effect=start_child_workflow) as start_child,
        patch(f"{GROUPING_MODULE_PATH}.workflow.uuid4", side_effect=signal_ids),
        patch(f"{GROUPING_MODULE_PATH}.uuid.uuid4", side_effect=signal_ids),
        patch(f"{GROUPING_MODULE_PATH}.workflow.patched", side_effect=patched),
    ):
        dropped, _ = await _process_signal_batch([_signal("promoted"), _signal("non-promoted")])

    assert dropped == 0
    assert [input.signal_id for input in assigned_inputs] == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    if expected_wait_indices:
        assert [signal.signal_id for signal in wait_inputs[0].signals] == [
            assigned_inputs[index].signal_id for index in expected_wait_indices
        ]
        assert wait_inputs[0].mode == WaitForClickHouseMode.CH_CONFIRMED
    else:
        assert wait_inputs == []

    if use_handoffs:
        expected_order = ["wait", "dispatch"] if expected_wait_indices else ["dispatch"]
        assert activity_order == expected_order
        assert len(dispatch_inputs) == 1
        assert dispatch_inputs[0].signal_keys == [f"handoff-{index + 1}" for index in sorted(handoff_indices)]
        start_child.assert_not_awaited()
    else:
        assert activity_order == ["wait", "child"]
        assert dispatch_inputs == []
        start_child.assert_awaited_once()
