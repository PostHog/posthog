import pytest
from unittest.mock import MagicMock, call, patch

from django.db import OperationalError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.db import db_read_with_retry

_CLOSE_CONNECTIONS_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.db.close_old_connections"
)
_SLEEP_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.db.time.sleep"


class TestDbReadWithRetry:
    def test_rides_out_pool_wait_timeout_then_succeeds(self):
        sentinel = object()
        fn = MagicMock(
            side_effect=[
                OperationalError("query_wait_timeout"),
                OperationalError("query_wait_timeout"),
                sentinel,
            ]
        )

        with patch(_CLOSE_CONNECTIONS_PATH) as close, patch(_SLEEP_PATH) as sleep:
            result = db_read_with_retry(fn)

        assert result is sentinel
        assert fn.call_count == 3
        # Connections evicted before every attempt, including the two that failed.
        assert close.call_count == 3
        # Backoff grows per `min(2 * attempt, 30)`: 2s after the 1st failure, 4s after the 2nd.
        assert sleep.call_args_list == [call(2), call(4)]

    def test_reraises_after_exhausting_attempts(self):
        fn = MagicMock(side_effect=OperationalError("query_wait_timeout"))

        with patch(_CLOSE_CONNECTIONS_PATH), patch(_SLEEP_PATH):
            with pytest.raises(OperationalError):
                db_read_with_retry(fn)

        assert fn.call_count == 4

    def test_non_operational_error_propagates_without_retry(self):
        fn = MagicMock(side_effect=ValueError("not a connection problem"))

        with patch(_CLOSE_CONNECTIONS_PATH), patch(_SLEEP_PATH) as sleep:
            with pytest.raises(ValueError):
                db_read_with_retry(fn)

        assert fn.call_count == 1
        sleep.assert_not_called()
