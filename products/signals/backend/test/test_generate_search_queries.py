import json

import pytest
from unittest.mock import patch

from products.signals.backend.temporal.grouping import (
    MAX_SEARCH_QUERIES,
    GenerateSearchQueriesInput,
    generate_search_queries,
)

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
