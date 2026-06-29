import contextlib

import pytest
from unittest import mock

from posthog.temporal.common.posthog_client import SKIP_ERROR_CAPTURE_ATTR

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common import extract
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import handle_non_retryable_error
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException


def _job_inputs() -> mock.MagicMock:
    job_inputs = mock.MagicMock()
    job_inputs.team_id = 1
    job_inputs.source_id = "source"
    job_inputs.run_id = "run"
    return job_inputs


@contextlib.contextmanager
def _patched_redis(incr_value: int):
    redis_client = mock.AsyncMock()
    redis_client.incr.return_value = incr_value

    @contextlib.asynccontextmanager
    async def _fake_redis():
        yield redis_client

    with mock.patch.object(extract, "_get_redis", _fake_redis):
        yield


@pytest.mark.asyncio
async def test_within_retry_limit_reraises_original_marked_for_skip_capture():
    # While retries remain, the original (retryable) error is re-raised so Temporal retries it,
    # but it is flagged so the interceptor doesn't report it to error tracking each attempt.
    original = ValueError("400 Client Error: Bad Request")

    with _patched_redis(incr_value=extract.NON_RETRYABLE_ERROR_RETRY_LIMIT):
        with pytest.raises(ValueError) as exc_info:
            await handle_non_retryable_error(_job_inputs(), "msg", mock.AsyncMock(), original)

    assert exc_info.value is original
    assert getattr(exc_info.value, SKIP_ERROR_CAPTURE_ATTR, False) is True


@pytest.mark.asyncio
async def test_beyond_retry_limit_raises_marked_non_retryable_exception():
    original = ValueError("400 Client Error: Bad Request")

    with _patched_redis(incr_value=extract.NON_RETRYABLE_ERROR_RETRY_LIMIT + 1):
        with pytest.raises(NonRetryableException) as exc_info:
            await handle_non_retryable_error(_job_inputs(), "msg", mock.AsyncMock(), original)

    assert getattr(exc_info.value, SKIP_ERROR_CAPTURE_ATTR, False) is True
    # The original provider error is preserved as the cause so it still reaches job status.
    assert exc_info.value.__cause__ is original


@pytest.mark.asyncio
async def test_missing_redis_raises_marked_non_retryable_exception():
    original = ValueError("400 Client Error: Bad Request")

    @contextlib.asynccontextmanager
    async def _no_redis():
        yield None

    with mock.patch.object(extract, "_get_redis", _no_redis):
        with pytest.raises(NonRetryableException) as exc_info:
            await handle_non_retryable_error(_job_inputs(), "msg", mock.AsyncMock(), original)

    assert getattr(exc_info.value, SKIP_ERROR_CAPTURE_ATTR, False) is True
    assert exc_info.value.__cause__ is original
