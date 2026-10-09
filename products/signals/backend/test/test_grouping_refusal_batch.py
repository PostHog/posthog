from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from products.signals.backend.temporal import grouping
from products.signals.backend.temporal.signal_queries import (
    FetchSignalTypeExamplesOutput,
    RunSignalSemanticSearchOutput,
)
from products.signals.backend.temporal.types import EmitSignalInputs, NewReportMatch, NoMatchMetadata


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quarantined,isolate_refusals,duplicate",
    [
        ((True, False), True, False),
        ((False, True), True, False),
        ((True, True), True, False),
        ((False, False), False, False),
        ((True, False), True, True),
    ],
)
async def test_quarantined_signals_do_not_block_healthy_batch_members(
    quarantined: tuple[bool, bool], isolate_refusals: bool, duplicate: bool
) -> None:
    batch = [
        EmitSignalInputs(team_id=1, source_product="test", source_type="issue", source_id=str(i), description=str(i))
        for i in range(2)
    ]
    if duplicate:
        batch.append(batch[0])
    query_requests: list[str] = []
    emitted: list[grouping.AssignAndEmitSignalInput] = []

    async def execute(activity: object, input: object, **kwargs: object) -> object:
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
            return None
        raise AssertionError(f"Unexpected activity: {activity}")

    with (
        patch.object(grouping.workflow, "execute_activity", side_effect=execute),
        patch.object(
            grouping.workflow,
            "patched",
            side_effect=lambda name: isolate_refusals and name == "signals-query-refusal-review-v1",
        ),
    ):
        dropped, _ = await grouping._process_signal_batch(batch, FetchSignalTypeExamplesOutput(examples=[]))

    assert dropped == sum(quarantined[int(signal.source_id)] for signal in batch)
    assert [signal.source_id for signal in emitted] == [
        signal.source_id for signal in batch if not quarantined[int(signal.source_id)]
    ]
    assert len(query_requests) == 2
