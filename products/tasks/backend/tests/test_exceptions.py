from products.tasks.backend.exceptions import (
    SANDBOX_RATE_LIMIT_BASE_DELAY_SECONDS,
    SANDBOX_RATE_LIMIT_MAX_DELAY_SECONDS,
    SandboxNotRunningError,
    SandboxRateLimitedError,
    sandbox_rate_limit_retry_delay,
)


def test_temporal_failure_type_defaults_to_class_name():
    error = SandboxNotRunningError("boom", {}, cause=RuntimeError("x"), capture=False)
    assert error.type == "SandboxNotRunningError"
    assert not error.non_retryable


def test_rate_limit_retry_delay_grows_with_the_attempt_and_is_capped():
    base = SANDBOX_RATE_LIMIT_BASE_DELAY_SECONDS

    assert all(base / 2 <= sandbox_rate_limit_retry_delay(1) <= base for _ in range(20))
    assert all(base <= sandbox_rate_limit_retry_delay(2) <= 2 * base for _ in range(20))
    assert all(sandbox_rate_limit_retry_delay(20) <= SANDBOX_RATE_LIMIT_MAX_DELAY_SECONDS for _ in range(20))


def test_rate_limit_error_is_retryable_and_carries_a_delay():
    error = SandboxRateLimitedError("rate limited", {"sandbox_id": "sb-1"})

    assert not error.non_retryable
    assert error.next_retry_delay is not None
