from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from anthropic.types import Message, TextBlock, Usage

from products.signals.backend.signal_costs import get_model_pricing, token_usage_to_spend
from products.signals.backend.temporal.llm import call_llm

MODULE_PATH = "products.signals.backend.signal_costs"
LLM_MODULE_PATH = "products.signals.backend.temporal.llm"


def test_token_usage_to_spend_prices_uncached_and_cached_anthropic_tokens() -> None:
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=200,
        cache_creation_input_tokens=100,
    )
    pricing = {
        "prompt": "0.0001",
        "completion": "0.0004",
        "input_cache_read": "0.00005",
        "input_cache_write": "0.0003",
    }

    assert token_usage_to_spend(usage, pricing) == 7


@pytest.mark.asyncio
async def test_model_pricing_catalogue_is_cached() -> None:
    model = SimpleNamespace(
        id="claude-test",
        pricing=SimpleNamespace(prompt="0.00001", completion="0.00002", input_cache_read="0.000001"),
    )
    client = MagicMock()
    client.with_options.return_value = client
    client.__aenter__.return_value = client
    client.models.list = AsyncMock(return_value=SimpleNamespace(data=[model]))

    with (
        patch(f"{MODULE_PATH}._model_pricings", None),
        patch(f"{MODULE_PATH}.build_async_openai_client", return_value=client),
        patch(f"{MODULE_PATH}.monotonic", return_value=0) as clock,
    ):
        first = await get_model_pricing("claude-test")
        second = await get_model_pricing("claude-test")
        with pytest.raises(LookupError, match="not priced"):
            await get_model_pricing("unknown-model")
        client.models.list.assert_awaited_once()
        client.with_options.assert_called_once_with(timeout=10, max_retries=0)
        clock.return_value = 3601
        model.pricing.prompt = "0.00003"
        refreshed = await get_model_pricing("claude-test")

    assert first == {"prompt": "0.00001", "completion": "0.00002", "input_cache_read": "0.000001"}
    assert second == first
    assert refreshed["prompt"] == "0.00003"
    assert client.models.list.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pricing",
    [
        pytest.param(
            SimpleNamespace(
                prompt="0.00001",
                completion="0.00002",
                input_cache_read="0.000001",
                input_cache_write="0.000004",
            ),
            id="python_gateway_rate_names",
        ),
        pytest.param(
            SimpleNamespace(
                prompt="0.00001",
                completion="0.00002",
                cache_read="0.000001",
                cache_write="0.000004",
            ),
            id="go_gateway_rate_names",
        ),
    ],
)
async def test_model_pricing_keeps_cache_rates_from_either_gateway(pricing: SimpleNamespace) -> None:
    client = MagicMock()
    client.with_options.return_value = client
    client.__aenter__.return_value = client
    client.models.list = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(id="claude-test", pricing=pricing)])
    )

    with (
        patch(f"{MODULE_PATH}._model_pricings", None),
        patch(f"{MODULE_PATH}.build_async_openai_client", return_value=client),
        patch(f"{MODULE_PATH}.monotonic", return_value=0),
    ):
        rates = await get_model_pricing("claude-test")

    assert rates == {
        "prompt": "0.00001",
        "completion": "0.00002",
        "input_cache_read": "0.000001",
        "input_cache_write": "0.000004",
    }


@pytest.mark.asyncio
async def test_model_pricing_reuses_a_requested_stale_price_after_refresh_error() -> None:
    client = MagicMock()
    client.with_options.return_value = client
    client.__aenter__.return_value = client
    client.models.list = AsyncMock(side_effect=RuntimeError("catalog unavailable"))
    cached_pricing = {"claude-test": {"prompt": "0.00001", "completion": "0.00002"}}

    with (
        patch(f"{MODULE_PATH}._model_pricings", cached_pricing),
        patch(f"{MODULE_PATH}._model_pricings_expires_at", 0),
        patch(f"{MODULE_PATH}.build_async_openai_client", return_value=client),
        patch(f"{MODULE_PATH}.monotonic", side_effect=[100, 100, 120, 161, 161]),
    ):
        first = await get_model_pricing("claude-test")
        second = await get_model_pricing("claude-test")
        refreshed = await get_model_pricing("claude-test")

    assert first == cached_pricing["claude-test"]
    assert second == first
    assert refreshed == first
    assert client.models.list.await_count == 2
    assert [call.kwargs for call in client.with_options.call_args_list] == [
        {"timeout": 10, "max_retries": 0},
        {"timeout": 10, "max_retries": 0},
    ]


@pytest.mark.asyncio
async def test_model_pricing_first_load_error_raises() -> None:
    client = MagicMock()
    client.with_options.return_value = client
    client.__aenter__.return_value = client
    client.models.list = AsyncMock(side_effect=RuntimeError("catalog unavailable"))

    with (
        patch(f"{MODULE_PATH}._model_pricings", None),
        patch(f"{MODULE_PATH}.build_async_openai_client", return_value=client),
        pytest.raises(RuntimeError, match="catalog unavailable"),
    ):
        await get_model_pricing("claude-test")


@pytest.mark.parametrize("price,expected", [("0.0049", 0), ("0.005", 1), ("0.0051", 1)])
def test_token_usage_to_spend_rounds_to_integer_cents(price: str, expected: int) -> None:
    assert token_usage_to_spend({"input_tokens": 1}, {"prompt": price}) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "validation_results, expected_cost",
    [([False, True], 1), ([False, False, False], 0)],
)
async def test_call_llm_records_only_the_response_that_passes_validation(
    validation_results: list[bool], expected_cost: int
) -> None:
    response = Message(
        id="msg_test",
        content=[TextBlock(text="ok", type="text")],
        model="claude-test",
        role="assistant",
        type="message",
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    attempts = 0

    def validate(_text: str) -> str:
        nonlocal attempts
        accepted = validation_results[attempts]
        attempts += 1
        if not accepted:
            raise ValueError("invalid")
        return "valid"

    costs: dict = {}
    with (
        patch(f"{LLM_MODULE_PATH}.get_async_anthropic_gateway_client", return_value=client),
        patch(
            f"{LLM_MODULE_PATH}.get_model_pricing",
            new=AsyncMock(return_value={"prompt": "0.005", "completion": "0.005"}),
        ),
    ):
        if expected_cost:
            result = await call_llm(
                team_id=1,
                system_prompt="s",
                user_prompt="u",
                validate=validate,
                costs=costs,
                retries=len(validation_results),
            )
            assert result == "valid"
        else:
            with pytest.raises(ValueError, match="invalid"):
                await call_llm(
                    team_id=1,
                    system_prompt="s",
                    user_prompt="u",
                    validate=validate,
                    costs=costs,
                    retries=len(validation_results),
                )

    if expected_cost:
        assert costs == {
            "token_cost": {"research": expected_cost, "implementation": 0},
            "compute_cost": {"research": 0, "implementation": 0},
        }
    else:
        assert costs == {}
