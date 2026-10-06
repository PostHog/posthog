import uuid
import contextlib
import dataclasses
from datetime import UTC, datetime

import pytest
import time_machine
from unittest import mock

import redis.exceptions as redis_exceptions
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.temporal.data_imports.retry_limits import RESUMABLE_IMPORT_DEADLINE
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import attempt_budget as module
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.attempt_budget import (
    ATTEMPTS_EXHAUSTED_ERROR_TYPE,
    FailedAttemptBudget,
)

HANDOFF = "handoff"
HANDOFF_REDIS_DOWN = "handoff_redis_down"
FAIL = "fail"
FAIL_REDIS_DOWN = "fail_redis_down"
NON_RETRYABLE = "non_retryable"
CRASH = "crash"
WAIT_FOR_DEADLINE = "wait_for_deadline"

RETRY = "retry"


def _stop(error_type: str) -> str:
    return f"stop:{error_type}"


def _error(step: str) -> Exception:
    if step in (HANDOFF, HANDOFF_REDIS_DOWN):
        return WorkerShuttingDownError("1", "import_data_activity_sync", "queue", 1, "workflow", "external-data-job")
    if step == NON_RETRYABLE:
        return NonRetryableException()
    return RuntimeError("boom")


def _unreachable_redis() -> mock.MagicMock:
    client = mock.MagicMock()
    client.get = mock.AsyncMock(side_effect=redis_exceptions.ConnectionError("down"))
    client.pipeline.return_value.execute = mock.AsyncMock(side_effect=redis_exceptions.ConnectionError("down"))
    return client


async def _run_attempt(run_id: str, attempt: int, step: str, *, limit: int | None, resumable: bool) -> str:
    logger = mock.MagicMock(ainfo=mock.AsyncMock(), awarning=mock.AsyncMock())
    error = _error(step)

    async def attempt_body() -> None:
        async with FailedAttemptBudget(team_id=1, run_id=run_id, limit=limit, logger=logger) as budget:
            if resumable:
                budget.mark_attempt_resumable()
            raise error

    environment = ActivityEnvironment()
    environment.info = dataclasses.replace(environment.info, attempt=attempt)
    redis_down = step in (HANDOFF_REDIS_DOWN, FAIL_REDIS_DOWN)
    redis_patch = mock.patch.object(module, "_redis", return_value=_unreachable_redis())
    with redis_patch if redis_down else contextlib.nullcontext():
        try:
            await environment.run(attempt_body)
        except ApplicationError as escaped:
            assert escaped.non_retryable
            if escaped.type != ATTEMPTS_EXHAUSTED_ERROR_TYPE:
                assert escaped.message == str(error)
                assert escaped.__cause__ is error
            return _stop(str(escaped.type))
        except Exception as escaped:
            assert escaped is error
            return RETRY
    raise AssertionError("the attempt raised nothing")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit,resumable,steps,expected",
    [
        pytest.param(
            2,
            True,
            [HANDOFF, HANDOFF, HANDOFF, FAIL, FAIL],
            [RETRY, RETRY, RETRY, RETRY, _stop("RuntimeError")],
            id="handoffs_from_a_resumable_attempt_are_free",
        ),
        pytest.param(
            2,
            False,
            [HANDOFF, HANDOFF],
            [RETRY, _stop("WorkerShuttingDownError")],
            id="handoffs_from_an_attempt_that_cannot_resume_are_charged",
        ),
        pytest.param(
            2,
            True,
            [HANDOFF_REDIS_DOWN, FAIL],
            [RETRY, _stop("RuntimeError")],
            id="a_handoff_redis_did_not_record_is_charged",
        ),
        pytest.param(
            2,
            True,
            [CRASH, CRASH, FAIL],
            [None, None, _stop(ATTEMPTS_EXHAUSTED_ERROR_TYPE)],
            id="attempts_that_died_without_an_error_are_charged",
        ),
        pytest.param(
            2,
            True,
            [CRASH, CRASH, FAIL_REDIS_DOWN],
            [None, None, RETRY],
            id="an_attempt_is_not_judged_while_redis_is_unreachable",
        ),
        pytest.param(
            2,
            True,
            [HANDOFF, HANDOFF, WAIT_FOR_DEADLINE, FAIL],
            [RETRY, RETRY, None, RETRY],
            id="the_handoff_count_outlives_the_import_deadline",
        ),
        pytest.param(
            1,
            True,
            [NON_RETRYABLE],
            [RETRY],
            id="an_error_temporal_already_stops_on_is_left_alone",
        ),
        pytest.param(
            None,
            True,
            [FAIL, FAIL, FAIL],
            [RETRY, RETRY, RETRY],
            id="no_limit_leaves_every_failure_to_the_retry_policy",
        ),
    ],
)
async def test_failed_attempt_budget(
    limit: int | None, resumable: bool, steps: list[str], expected: list[str | None]
) -> None:
    run_id = str(uuid.uuid4())
    outcomes: list[str | None] = []

    attempt = 0

    with time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False) as clock:
        for step in steps:
            if step == WAIT_FOR_DEADLINE:
                clock.shift(RESUMABLE_IMPORT_DEADLINE)
                outcomes.append(None)
                continue
            attempt += 1
            if step == CRASH:
                outcomes.append(None)
                continue
            outcomes.append(await _run_attempt(run_id, attempt, step, limit=limit, resumable=resumable))

    assert outcomes == expected
