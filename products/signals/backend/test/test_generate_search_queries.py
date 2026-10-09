import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from anthropic.types import Message, TextBlock, Usage

from products.signals.backend.temporal.grouping import (
    MAX_SEARCH_QUERIES,
    GenerateSearchQueriesInput,
    generate_search_queries,
    generate_search_queries_activity,
)
from products.signals.backend.temporal.llm import EmptyLLMResponseError
from products.signals.backend.temporal.types import EmitSignalInputs

MODULE_PATH = "products.signals.backend.temporal.grouping"


@pytest.mark.asyncio
@pytest.mark.parametrize("returned", [3, 5])
async def test_generate_search_queries_keeps_the_first_three_without_a_retry(returned):
    queries = [f"query {i}" for i in range(returned)]

    async def fake_call_llm(**kwargs):
        return kwargs["validate"](json.dumps({"queries": queries}))

    with patch(f"{MODULE_PATH}.call_llm", side_effect=fake_call_llm) as call_llm:
        result = await generate_search_queries(
            GenerateSearchQueriesInput(
                description="Date picker shows the wrong day",
                source_product="zendesk",
                source_type="ticket",
                signal_type_examples=[],
            )
        )

    assert result == queries[:MAX_SEARCH_QUERIES]
    assert call_llm.call_count == 1


@pytest.mark.asyncio
async def test_generate_search_queries_leaves_empty_response_handling_to_the_activity() -> None:
    with patch(f"{MODULE_PATH}.call_llm", side_effect=EmptyLLMResponseError("No text content in response")):
        with pytest.raises(EmptyLLMResponseError):
            await generate_search_queries(
                GenerateSearchQueriesInput(
                    description="Date picker shows the wrong day",
                    source_product="test",
                    source_type="ticket",
                    signal_type_examples=[],
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("refusals", [2, 3])
async def test_activity_preserves_only_signals_that_exhaust_refusal_attempts(refusals: int) -> None:
    refused = Message(
        id="msg_test",
        content=[],
        stop_reason="refusal",
        model="claude-sonnet-5-5",
        role="assistant",
        type="message",
        usage=Usage(input_tokens=1, output_tokens=0),
    )
    accepted = refused.model_copy(
        update={"content": [TextBlock(type="text", text='{"queries": ["date picker"]}')], "stop_reason": "end_turn"}
    )
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=[refused] * refusals + [accepted])
    signal = EmitSignalInputs(
        team_id=1, source_product="test", source_type="ticket", source_id="example", description="Date picker fails"
    )
    with (
        patch("products.signals.backend.temporal.llm.build_async_anthropic_client", return_value=client),
        patch("products.signals.backend.temporal.refusal_review.object_storage.read", return_value=None),
        patch("products.signals.backend.temporal.refusal_review.object_storage.write"),
        patch("products.signals.backend.temporal.refusal_review.object_storage.delete"),
    ):
        result = await generate_search_queries_activity(
            GenerateSearchQueriesInput(
                team_id=1,
                description=signal.description,
                source_product=signal.source_product,
                source_type=signal.source_type,
                signal_type_examples=[],
                signal=signal,
            )
        )

    assert result.quarantined is (refusals == 3)
    assert result.queries == ([] if refusals == 3 else ["date picker"])
    assert client.messages.create.await_count == 3
