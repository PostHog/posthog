import json
from collections.abc import Generator

import pytest
from unittest.mock import AsyncMock, patch

from products.signals.backend.temporal import llm
from products.signals.backend.temporal.refusal_review import generate_queries_or_preserve_refusal, refusal_review_key
from products.signals.backend.temporal.types import EmitSignalInputs

MODULE = "products.signals.backend.temporal.refusal_review"


@pytest.fixture
def stored_records() -> Generator[dict[str, str]]:
    records: dict[str, str] = {}
    with (
        patch(f"{MODULE}.object_storage.read", side_effect=lambda key, **kwargs: records.get(key)),
        patch(f"{MODULE}.object_storage.write", side_effect=lambda key, value: records.__setitem__(key, value)),
        patch(f"{MODULE}.object_storage.delete", side_effect=lambda key: records.pop(key)),
    ):
        yield records


def make_signal() -> EmitSignalInputs:
    return EmitSignalInputs(
        team_id=1,
        source_product="test",
        source_type="issue",
        source_id="example-1",
        description="The settings page does not save a new display name.",
        extra={"url": "https://example.com/issues/1"},
        remediation={"instructions": "Check the save action."},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("refusals", [1, 2])
async def test_noisy_refusal_can_recover_before_review(stored_records: dict[str, str], refusals: int) -> None:
    signal = make_signal()
    generate = AsyncMock(side_effect=[llm.LLMRefusalError()] * refusals + [["settings save"]])

    assert await generate_queries_or_preserve_refusal(signal, generate) == ["settings save"]
    assert generate.await_count == refusals + 1
    assert not stored_records


@pytest.mark.asyncio
async def test_three_refusals_preserve_the_signal_and_skip_batch_retries(stored_records: dict[str, str]) -> None:
    signal = make_signal()
    generate = AsyncMock(side_effect=llm.LLMRefusalError())

    assert await generate_queries_or_preserve_refusal(signal, generate) is None
    record = json.loads(stored_records[refusal_review_key(signal)])
    assert record["status"] == "needs_review"
    assert record["attempts"] == 3
    assert EmitSignalInputs(**record["signal"]) == signal
    assert await generate_queries_or_preserve_refusal(signal, generate) is None
    assert generate.await_count == 3


@pytest.mark.asyncio
async def test_refusal_count_survives_an_unrelated_failure(stored_records: dict[str, str]) -> None:
    signal = make_signal()
    generate = AsyncMock(side_effect=[llm.LLMRefusalError(), ConnectionError()])
    with pytest.raises(ConnectionError):
        await generate_queries_or_preserve_refusal(signal, generate)

    generate = AsyncMock(side_effect=llm.LLMRefusalError())
    assert await generate_queries_or_preserve_refusal(signal, generate) is None
    assert generate.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [llm.EmptyLLMResponseError(), ConnectionError()])
async def test_other_errors_still_fail_the_activity(stored_records: dict[str, str], error: Exception) -> None:
    generate = AsyncMock(side_effect=error)
    with pytest.raises(type(error)):
        await generate_queries_or_preserve_refusal(make_signal(), generate)
    assert not stored_records


@pytest.mark.asyncio
async def test_storage_failure_cannot_remove_the_signal(stored_records: dict[str, str]) -> None:
    generate = AsyncMock(side_effect=llm.LLMRefusalError())
    with patch(f"{MODULE}.object_storage.write", side_effect=ConnectionError()), pytest.raises(ConnectionError):
        await generate_queries_or_preserve_refusal(make_signal(), generate)
    assert not stored_records
