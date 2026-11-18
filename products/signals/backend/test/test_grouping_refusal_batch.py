from datetime import UTC, datetime

import pytest
from unittest.mock import Mock, patch

from temporalio.exceptions import ActivityError, RetryState

from products.signals.backend.temporal import grouping
from products.signals.backend.temporal.signal_queries import (
    FetchSignalTypeExamplesOutput,
    RunSignalSemanticSearchOutput,
)
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    ExistingReportMatch,
    MatchedMetadata,
    NewReportMatch,
    NoMatchMetadata,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quarantined,isolate_refusals,duplicate,failure_at",
    [
        ((True, False), True, False, None),
        ((False, True), True, False, None),
        ((True, True), True, False, None),
        ((False, False), False, False, None),
        ((True, False), True, True, None),
        ((False, False), True, False, "get_embedding_activity"),
        ((False, False), True, False, "wait_for_signal_in_clickhouse_activity"),
        ((False, False), True, False, "complete_signal_grouping_activity"),
    ],
)
async def test_quarantined_signals_do_not_block_healthy_batch_members(
    quarantined: tuple[bool, bool], isolate_refusals: bool, duplicate: bool, failure_at: str | None
) -> None:
    batch = [
        EmitSignalInputs(
            team_id=1,
            signal_id=str(i),
            source_product="test",
            source_type="issue",
            source_id=str(i),
            description=str(i),
        )
        for i in range(2)
    ]
    if duplicate:
        batch.append(batch[0])
    batch.append(
        EmitSignalInputs(
            team_id=1,
            source_product="github",
            source_type="issue",
            source_id="source-sync",
            signal_id="source-sync",
            description="2",
            sync_with_source=True,
            source_match_signal_id="previous-signal",
            source_match_report_id="existing-report",
        )
    )
    query_requests: list[str] = []
    emitted: list[grouping.AssignAndEmitSignalInput] = []

    completions: list[grouping.SignalGroupingCompletion] = []
    visibility_confirmed = False

    async def execute(activity: object, input: object, **kwargs: object) -> object:
        nonlocal visibility_confirmed
        if failure_at is not None and getattr(activity, "__name__", None) == failure_at:
            raise ActivityError(
                "failed",
                scheduled_event_id=1,
                started_event_id=2,
                identity="test",
                activity_type=failure_at,
                activity_id="test",
                retry_state=RetryState.TIMEOUT,
            )
        if activity == grouping.complete_signal_grouping_activity:
            assert visibility_confirmed
            assert isinstance(input, list)
            completions.extend(input)
            return None
        if activity == grouping.get_embedding_activity:
            assert isinstance(input, grouping.GenerateEmbeddingInput)
            return grouping.GenerateEmbeddingOutput(embedding=[float(input.content)])
        if activity == grouping.generate_search_queries_activity:
            assert isinstance(input, grouping.GenerateSearchQueriesInput)
            assert (input.signal is not None) is isolate_refusals
            query_requests.append(input.description)
            i = int(input.description)
            return grouping.GenerateSearchQueriesOutput(
                queries=[] if quarantined[i] else [str(i)], quarantined=quarantined[i]
            )
        if activity == grouping.run_signal_semantic_search_activity:
            return RunSignalSemanticSearchOutput(candidates=[])
        if activity == grouping.fetch_report_contexts_activity:
            return grouping.FetchReportContextsOutput(contexts={})
        if activity == grouping.match_signal_to_report_activity:
            assert isinstance(input, grouping.MatchSignalToReportInput)
            if input.source_id == "source-sync":
                assert input.queries == []
                assert input.source_match_signal_id == "previous-signal"
                assert input.source_match_report_id == "existing-report"
                return ExistingReportMatch(
                    report_id="existing-report",
                    match_metadata=MatchedMetadata(
                        parent_signal_id="previous-signal",
                        match_query="source identity",
                        reason="source update",
                    ),
                    source_synced=True,
                )
            assert input.queries == [input.description]
            return NewReportMatch(
                title="Example report", summary="Example summary", match_metadata=NoMatchMetadata(reason="new")
            )
        if activity == grouping.assign_and_emit_signal_activity:
            assert isinstance(input, grouping.AssignAndEmitSignalInput)
            assert input.embedding == [float(input.description)]
            emitted.append(input)
            return grouping.AssignAndEmitSignalOutput(
                report_id="report", promoted=False, timestamp=datetime.now(UTC), run_count=0
            )
        if activity == grouping.wait_for_signal_in_clickhouse_activity:
            visibility_confirmed = True
            return None
        raise AssertionError(f"Unexpected activity: {activity}")

    with (
        patch.object(grouping.workflow, "execute_activity", side_effect=execute),
        patch.object(
            grouping.workflow,
            "patched",
            side_effect=lambda name: (
                name == "signals-owner-spend-grouping-completion"
                or (isolate_refusals and name == "signals-query-refusal-review-v1")
            ),
        ),
    ):
        if failure_at in {"get_embedding_activity", "wait_for_signal_in_clickhouse_activity"}:
            with pytest.raises(ActivityError):
                await grouping._process_signal_batch(batch, FetchSignalTypeExamplesOutput(examples=[]))
            assert completions == []
            return
        with patch.object(grouping.workflow, "logger", Mock()):
            dropped, _ = await grouping._process_signal_batch(batch, FetchSignalTypeExamplesOutput(examples=[]))
        if failure_at is None:
            assert [item.signal_id for item in completions] == [signal.signal_id for signal in batch]

    assert dropped == sum(quarantined[int(signal.source_id)] for signal in batch if signal.source_id != "source-sync")
    assert [signal.source_id for signal in emitted] == [
        signal.source_id
        for signal in batch
        if signal.source_id == "source-sync" or not quarantined[int(signal.source_id)]
    ]
    assert len(query_requests) == 2
