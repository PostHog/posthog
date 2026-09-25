import pytest
from unittest.mock import AsyncMock, patch

from products.signals.backend.temporal.grouping import (
    FetchReportContextsOutput,
    GenerateEmbeddingOutput,
    GenerateSearchQueriesOutput,
    _process_signal_batch,
)
from products.signals.backend.temporal.parallel_grouping import SequentialPhaseResult
from products.signals.backend.temporal.signal_queries import (
    FetchSignalTypeExamplesOutput,
    RunSignalSemanticSearchOutput,
    run_signal_semantic_search_activity,
)
from products.signals.backend.temporal.types import EmitSignalInputs

GROUPING_MODULE = "products.signals.backend.temporal.grouping"
PARALLEL_GROUPING_MODULE = "products.signals.backend.temporal.parallel_grouping"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch_active,expected_lookup_embeddings",
    [(False, [[0.0, 1.0]]), (True, [[1.0, 0.0], [0.0, 1.0]])],
)
async def test_signal_embedding_is_used_for_semantic_lookup(
    patch_active: bool, expected_lookup_embeddings: list[list[float]]
) -> None:
    signal_embedding = [1.0, 0.0]
    query_embedding = [0.0, 1.0]
    signal = EmitSignalInputs(
        team_id=1,
        source_product="error_tracking",
        source_type="issue",
        source_id="source-1",
        description="Checkout requests fail after payment",
    )

    with (
        patch(f"{GROUPING_MODULE}.workflow.execute_activity", new_callable=AsyncMock) as execute_activity,
        patch(f"{GROUPING_MODULE}.workflow.patched", side_effect=[patch_active, True]),
        patch(
            f"{PARALLEL_GROUPING_MODULE}.process_sequential_phase_parallel",
            new_callable=AsyncMock,
            return_value=SequentialPhaseResult(dropped=0, promoted_reports={}, emitted_signals=[]),
        ),
    ):
        search_results = [RunSignalSemanticSearchOutput(candidates=[])] * (2 if patch_active else 1)
        execute_activity.side_effect = [
            GenerateEmbeddingOutput(embedding=signal_embedding),
            GenerateSearchQueriesOutput(queries=["Payment failures during checkout"]),
            GenerateEmbeddingOutput(embedding=query_embedding),
            *search_results,
            FetchReportContextsOutput(contexts={}),
        ]
        await _process_signal_batch([signal], cached_type_examples=FetchSignalTypeExamplesOutput(examples=[]))

    lookup_embeddings = [
        call.args[1].embedding
        for call in execute_activity.await_args_list
        if call.args[0] is run_signal_semantic_search_activity
    ]
    assert lookup_embeddings == expected_lookup_embeddings
