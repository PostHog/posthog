import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pydantic
from anthropic import APIStatusError
from pydantic import TypeAdapter
from temporalio.exceptions import ApplicationError

from products.review_hog.backend.reviewer.constants import ONESHOT_MODEL, ONESHOT_REASONING_EFFORT
from products.review_hog.backend.reviewer.models.issue_deduplicator import IssueDeduplication
from products.review_hog.backend.reviewer.sandbox.direct_llm import run_oneshot_review

_MODULE = "products.review_hog.backend.reviewer.sandbox.direct_llm"


def _api_error(status: int) -> APIStatusError:
    request = httpx.Request("POST", "http://gateway/review_hog/v1/messages")
    return APIStatusError("boom", response=httpx.Response(status, request=request), body=None)


def _mock_client(parse: AsyncMock) -> AsyncMock:
    client = AsyncMock()
    client.messages.parse = parse
    return client


async def _call() -> IssueDeduplication:
    return await run_oneshot_review(
        team_id=1,
        user_id=2,
        prompt="the prompt",
        system_prompt="the system prompt",
        model_to_validate=IssueDeduplication,
        step_name="dedup",
    )


@pytest.mark.asyncio
async def test_oneshot_call_pins_model_effort_schema_and_stage() -> None:
    # The one-shot value proposition rides on this request shape: dropping the model/effort pin
    # silently falls back to the gateway default, dropping output_format loses the schema guarantee,
    # and dropping the stage header makes the call unattributable in dumps and cost queries.
    parsed = IssueDeduplication(duplicates=[])
    mock_parse = AsyncMock(return_value=MagicMock(parsed_output=parsed))

    with patch(f"{_MODULE}.get_async_anthropic_gateway_client", return_value=_mock_client(mock_parse)) as mock_get:
        result = await _call()

    assert result is parsed
    assert mock_get.call_args.kwargs["product"] == "review_hog"
    assert mock_get.call_args.kwargs["team_id"] == 1
    kwargs = mock_parse.call_args.kwargs
    assert kwargs["model"] == ONESHOT_MODEL
    assert kwargs["output_config"] == {"effort": ONESHOT_REASONING_EFFORT}
    assert kwargs["output_format"] is IssueDeduplication
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["system"] == "the system prompt"
    assert kwargs["messages"] == [{"role": "user", "content": "the prompt"}]
    assert kwargs["extra_headers"] == {"x-posthog-property-ai_stage": "dedup"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,non_retryable",
    [
        (400, True),  # schema/request rejected — retrying re-sends the same bad request forever
        (408, False),
        (429, False),
        (500, False),
    ],
)
async def test_api_errors_map_to_temporal_retryability(status: int, non_retryable: bool) -> None:
    mock_parse = AsyncMock(side_effect=_api_error(status))

    with (
        patch(f"{_MODULE}.get_async_anthropic_gateway_client", return_value=_mock_client(mock_parse)),
        pytest.raises(ApplicationError) as exc_info,
    ):
        await _call()

    assert exc_info.value.non_retryable is non_retryable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stop_reason,non_retryable",
    [
        ("refusal", False),  # a flake worth one more attempt
        ("max_tokens", True),  # deterministic truncation — a retry resubmits the same doomed prompt
    ],
)
async def test_no_parseable_output_retryability_branches_on_stop_reason(stop_reason: str, non_retryable: bool) -> None:
    # No parsed output must raise (never return None into the pipeline), and the retry decision
    # must follow the stop reason.
    mock_parse = AsyncMock(return_value=MagicMock(parsed_output=None, stop_reason=stop_reason))

    with (
        patch(f"{_MODULE}.get_async_anthropic_gateway_client", return_value=_mock_client(mock_parse)),
        pytest.raises(ApplicationError) as exc_info,
    ):
        await _call()

    assert exc_info.value.non_retryable is non_retryable
    assert stop_reason in str(exc_info.value)


def _validation_error() -> pydantic.ValidationError:
    try:
        TypeAdapter(IssueDeduplication).validate_json('{"duplicates": [')
    except pydantic.ValidationError as e:
        return e
    raise AssertionError("truncated JSON unexpectedly validated")


@pytest.mark.asyncio
async def test_truncated_json_validation_error_becomes_a_compact_application_error() -> None:
    # The SDK validates the text block inside messages.parse(), so truncated JSON raises a raw
    # pydantic.ValidationError there — past the APIError handler and before parsed_output exists.
    # It must surface as the documented compact ApplicationError (retryable, stage-attributed),
    # not an oversized unclassified exception that Temporal's failure serialization chokes on.
    mock_parse = AsyncMock(side_effect=_validation_error())

    with (
        patch(f"{_MODULE}.get_async_anthropic_gateway_client", return_value=_mock_client(mock_parse)),
        pytest.raises(ApplicationError) as exc_info,
    ):
        await _call()

    assert exc_info.value.non_retryable is False
    assert "dedup" in str(exc_info.value)
