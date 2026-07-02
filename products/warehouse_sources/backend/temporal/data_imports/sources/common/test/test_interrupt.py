import pytest
from unittest import mock

from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.interrupt import raise_if_interrupted
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.interrupt.activity"


def test_raise_if_interrupted_is_noop_outside_activity():
    with mock.patch(f"{_MODULE}.in_activity", return_value=False):
        raise_if_interrupted()


def test_raise_if_interrupted_raises_on_worker_shutdown():
    with (
        mock.patch(f"{_MODULE}.in_activity", return_value=True),
        mock.patch(f"{_MODULE}.is_worker_shutdown", return_value=True),
        mock.patch(
            "posthog.temporal.common.shutdown.WorkerShuttingDownError.from_activity_context",
            return_value=WorkerShuttingDownError("a", "b", "q", 1, "w", "wt"),
        ),
    ):
        with pytest.raises(WorkerShuttingDownError):
            raise_if_interrupted()


def test_raise_if_interrupted_raises_non_retryable_on_cancel():
    with (
        mock.patch(f"{_MODULE}.in_activity", return_value=True),
        mock.patch(f"{_MODULE}.is_worker_shutdown", return_value=False),
        mock.patch(f"{_MODULE}.is_cancelled", return_value=True),
    ):
        with pytest.raises(NonRetryableException):
            raise_if_interrupted()
