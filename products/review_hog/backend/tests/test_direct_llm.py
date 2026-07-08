import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
from pydantic import BaseModel, TypeAdapter
from temporalio.exceptions import ApplicationError

from products.review_hog.backend.reviewer.sandbox.direct_llm import run_oneshot_review


class _Out(BaseModel):
    ids: list[str]


def _validation_error() -> pydantic.ValidationError:
    try:
        TypeAdapter(_Out).validate_json('{"ids": [')
    except pydantic.ValidationError as e:
        return e
    raise AssertionError("truncated JSON unexpectedly validated")


def _client(parse: AsyncMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__.return_value = client
    client.messages.parse = parse
    return client


async def _run(parse: AsyncMock) -> _Out:
    with patch(
        "products.review_hog.backend.reviewer.sandbox.direct_llm.get_async_anthropic_gateway_client",
        return_value=_client(parse),
    ):
        return await run_oneshot_review(
            team_id=1, user_id=2, prompt="p", system_prompt="s", model_to_validate=_Out, step_name="dedup"
        )


# A max_tokens truncation is deterministic — retrying the same oversized prompt hits the same wall —
# while a refusal is a flake worth one more attempt. Regressing this burns the whole Temporal retry
# budget (600s + up to 64K output tokens per attempt) on a failure a retry can never fix.
@pytest.mark.parametrize("stop_reason,non_retryable", [("max_tokens", True), ("refusal", False)])
async def test_unparsed_output_retryability_branches_on_stop_reason(stop_reason: str, non_retryable: bool) -> None:
    parse = AsyncMock(return_value=MagicMock(parsed_output=None, stop_reason=stop_reason))

    with pytest.raises(ApplicationError) as err:
        await _run(parse)

    assert err.value.non_retryable is non_retryable
    assert stop_reason in str(err.value)


async def test_truncated_json_validation_error_becomes_a_compact_application_error() -> None:
    # The SDK validates the text block inside messages.parse(), so truncated JSON raises a raw
    # pydantic.ValidationError there — past the APIError handler and before parsed_output exists.
    # It must surface as the documented compact ApplicationError, not an oversized unclassified
    # exception that Temporal's failure serialization chokes on.
    parse = AsyncMock(side_effect=_validation_error())

    with pytest.raises(ApplicationError) as err:
        await _run(parse)

    assert err.value.non_retryable is False
    assert "dedup" in str(err.value)
