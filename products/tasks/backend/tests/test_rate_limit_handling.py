"""Tests for upstream-LLM rate-limit detection in the sandbox-agent runner.

The sandbox's `Task` runs the LLM agent in a Modal-hosted subprocess. When the
upstream provider (Anthropic, OpenAI, etc.) returns HTTP 429, the agent crashes
and the TaskRun is marked `failed` with the upstream error text in
`error_message`. Without the typed exception added here, this would surface to
the caller as a generic `RuntimeError` and any work already done in the agent
loop would be discarded. These tests cover the classification, the Retry-After
parsing, and `_drain_final_log` raising the typed exception.
"""

import pytest
from unittest.mock import AsyncMock, patch

from products.tasks.backend.services.custom_prompt_internals import (
    RateLimitedError,
    _drain_final_log,
    _parse_rate_limit_from_error_message,
)
from products.tasks.backend.tests.agent_log_fixtures import FakeTaskRun


class TestParseRateLimitFromErrorMessage:
    @pytest.mark.parametrize(
        "error_message",
        [
            # The exact string seen in the production incident (Anthropic via claude-agent-sdk).
            "Internal error: API Error: Request rejected (429) · Rate limit exceeded",
            "HTTP 429 - Too Many Requests",
            "rate_limit_exceeded: anthropic-input-tokens-per-minute exhausted",
            "anthropic.RateLimitError: Error code: 429",
            "Rate limit reached for requests",
        ],
    )
    def test_classifies_429_messages_as_rate_limited(self, error_message):
        is_rate_limited, retry_after = _parse_rate_limit_from_error_message(error_message)
        assert is_rate_limited is True
        # No Retry-After value present in these — the classifier still flags the cluster.
        assert retry_after is None

    @pytest.mark.parametrize(
        "error_message",
        [
            None,
            "",
            "Internal error: connection reset by peer",
            "ValidationError: missing field 'signal_id'",
            "TimeoutError: agent failed to respond within 30s",
            # 429 substring inside something that isn't a rate-limit error (e.g. a hash).
            "Encountered hash mismatch 42942a in cache lookup",
        ],
    )
    def test_does_not_classify_unrelated_messages(self, error_message):
        is_rate_limited, retry_after = _parse_rate_limit_from_error_message(error_message)
        assert is_rate_limited is False
        assert retry_after is None

    @pytest.mark.parametrize(
        "error_message,expected_seconds",
        [
            # HTTP header form
            ("HTTP 429. Retry-After: 30", 30.0),
            ("Rate limited. retry-after: 5", 5.0),
            # SDK structured form
            ("anthropic.RateLimitError: 429, retry_after=42", 42.0),
            ("Too many requests, retry_after = 12.5", 12.5),
            # Free-form prose
            ("Rate limit exceeded — please retry in 7 seconds", 7.0),
            ("HTTP 429: retry after 90 seconds", 90.0),
            # Units other than bare seconds
            ("429 Too Many Requests, retry-after: 500ms", 0.5),
            ("Rate limit hit, retry after 2 minutes", 120.0),
        ],
    )
    def test_extracts_retry_after_seconds(self, error_message, expected_seconds):
        is_rate_limited, retry_after = _parse_rate_limit_from_error_message(error_message)
        assert is_rate_limited is True
        assert retry_after == pytest.approx(expected_seconds)

    def test_negative_retry_after_is_dropped(self):
        """A negative Retry-After is nonsensical and should fall back to the default
        backoff rather than being honored as-is."""
        is_rate_limited, retry_after = _parse_rate_limit_from_error_message("HTTP 429. retry_after=-5")
        assert is_rate_limited is True
        assert retry_after is None


class TestDrainFinalLogRateLimit:
    @pytest.mark.asyncio
    async def test_raises_rate_limited_error_for_429_cause(self):
        """The signal-report incident: TaskRun terminates with a 429 cause and no
        agent message recoverable from S3. `_drain_final_log` must raise the typed
        `RateLimitedError` so `MultiTurnSession.start` can wait and retry."""
        with (
            patch("posthog.storage.object_storage.read", return_value=""),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            with pytest.raises(RateLimitedError) as exc_info:
                await _drain_final_log(
                    FakeTaskRun(),
                    refreshed_status="failed",
                    error_message=("Internal error: API Error: Request rejected (429) · Rate limit exceeded"),
                    skip_lines=0,
                    printed_lines=0,
                    verbose=False,
                    output_fn=None,
                )

        # No Retry-After in the upstream message → typed exception with None retry_after.
        # MultiTurnSession will fall back to exponential backoff with jitter.
        assert exc_info.value.retry_after_seconds is None
        assert "Rate limit exceeded" in str(exc_info.value)
        assert "status=failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_rate_limited_error_with_parsed_retry_after(self):
        """When the upstream error carries Retry-After, it must reach the caller so
        we honor the provider's suggested wait rather than guessing."""
        with (
            patch("posthog.storage.object_storage.read", return_value=""),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            with pytest.raises(RateLimitedError) as exc_info:
                await _drain_final_log(
                    FakeTaskRun(),
                    refreshed_status="failed",
                    error_message="HTTP 429 Too Many Requests. Retry-After: 25",
                    skip_lines=0,
                    printed_lines=0,
                    verbose=False,
                    output_fn=None,
                )

        assert exc_info.value.retry_after_seconds == pytest.approx(25.0)

    @pytest.mark.asyncio
    async def test_raises_plain_runtime_error_for_non_rate_limit_causes(self):
        """Regression guard: non-429 failures must keep raising `RuntimeError` so we
        don't accidentally retry transient validation or auth errors as if they were
        rate limits."""
        with (
            patch("posthog.storage.object_storage.read", return_value=""),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await _drain_final_log(
                    FakeTaskRun(),
                    refreshed_status="failed",
                    error_message="ValidationError: missing field 'signal_id'",
                    skip_lines=0,
                    printed_lines=0,
                    verbose=False,
                    output_fn=None,
                )

        # Crucial: NOT a `RateLimitedError`. A bare `RuntimeError`.
        assert not isinstance(exc_info.value, RateLimitedError)
