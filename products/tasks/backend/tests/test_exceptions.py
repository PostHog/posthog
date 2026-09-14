import dataclasses
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.testing import ActivityEnvironment

from products.tasks.backend.exceptions import SandboxNotRunningError, SandboxRateLimitedError


@activity.defn
def _shed_by_the_proxy() -> None:
    raise SandboxRateLimitedError("x", {})


def test_temporal_failure_type_defaults_to_class_name():
    error = SandboxNotRunningError("boom", {}, cause=RuntimeError("x"), capture=False)
    assert error.type == "SandboxNotRunningError"
    assert not error.non_retryable


@pytest.mark.parametrize(
    "attempt,expected_floor,expected_ceiling",
    [
        (1, 22.5, 45.0),
        (2, 45.0, 90.0),
        (3, 90.0, 180.0),
        (6, 150.0, 300.0),
    ],
)
def test_rate_limit_backoff_follows_the_activity_attempt(attempt: int, expected_floor: float, expected_ceiling: float):
    environment = ActivityEnvironment()
    environment.info = dataclasses.replace(environment.info, attempt=attempt)

    with pytest.raises(SandboxRateLimitedError) as error:
        environment.run(_shed_by_the_proxy)

    assert error.value.non_retryable is False
    assert error.value.next_retry_delay is not None
    assert timedelta(seconds=expected_floor) <= error.value.next_retry_delay <= timedelta(seconds=expected_ceiling)
