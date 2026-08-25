import pytest
from unittest import mock
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry import (
    retry_on_operational_error,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry"


class TestRetryOnOperationalError(SimpleTestCase):
    def test_retries_transient_operational_error_then_succeeds(self):
        fn = mock.Mock(
            side_effect=[
                OperationalError("query_wait_timeout"),
                OperationalError("query_wait_timeout"),
                "result",
            ]
        )

        with (
            patch(f"{_MODULE}.close_old_connections") as close,
            patch(f"{_MODULE}.time.sleep") as sleep,
        ):
            result = retry_on_operational_error(fn)()

        assert result == "result"
        assert fn.call_count == 3
        # The poisoned connection is evicted before each retry, but not on the successful attempt.
        assert close.call_count == 2
        # Backoff grows per `min(2 * attempt, 30)`: 2s after the 1st failure, 4s after the 2nd.
        assert sleep.call_args_list == [mock.call(2), mock.call(4)]

    def test_success_does_not_evict_connection(self):
        fn = mock.Mock(return_value="result")

        with (
            patch(f"{_MODULE}.close_old_connections") as close,
            patch(f"{_MODULE}.time.sleep") as sleep,
        ):
            result = retry_on_operational_error(fn)()

        assert result == "result"
        close.assert_not_called()
        sleep.assert_not_called()

    def test_reraises_after_exhausting_attempts(self):
        fn = mock.Mock(side_effect=OperationalError("query_wait_timeout"))

        with (
            patch(f"{_MODULE}.close_old_connections"),
            patch(f"{_MODULE}.time.sleep") as sleep,
        ):
            with pytest.raises(OperationalError):
                retry_on_operational_error(fn)()

        # Bounded attempts: it gives up rather than looping forever, leaving Temporal to retry the activity.
        assert fn.call_count == 4
        assert sleep.call_args_list == [mock.call(2), mock.call(4), mock.call(6)]

    def test_passes_through_args_and_kwargs(self):
        fn = mock.Mock(return_value="result")

        result = retry_on_operational_error(fn)(1, 2, key="value")

        fn.assert_called_once_with(1, 2, key="value")
        assert result == "result"
