import pytest
from unittest.mock import MagicMock, patch

from django.db import OperationalError

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.util import retry_on_db_pool_timeout

_UTIL = "products.warehouse_sources.backend.temporal.data_imports.util"


class TestRetryOnDbPoolTimeout:
    def test_returns_result_without_retrying_on_success(self) -> None:
        operation = MagicMock(return_value="ok")
        with patch(f"{_UTIL}.close_old_connections") as close, patch(f"{_UTIL}.time.sleep"):
            assert retry_on_db_pool_timeout(operation, MagicMock()) == "ok"
        assert operation.call_count == 1
        close.assert_not_called()

    @parameterized.expand(
        [
            ("query_wait_timeout", OperationalError("ProtocolViolation: query_wait_timeout")),
            ("connection_closed", OperationalError("the connection is closed")),
        ]
    )
    def test_retries_transient_pool_error_then_succeeds(self, _name: str, error: OperationalError) -> None:
        operation = MagicMock(side_effect=[error, error, "ok"])
        with patch(f"{_UTIL}.close_old_connections") as close, patch(f"{_UTIL}.time.sleep"):
            assert retry_on_db_pool_timeout(operation, MagicMock()) == "ok"
        assert operation.call_count == 3
        # The connection is refreshed before each retry so the next attempt grabs a live one.
        assert close.call_count == 2

    def test_reraises_after_exhausting_attempts(self) -> None:
        operation = MagicMock(side_effect=OperationalError("query_wait_timeout"))
        with patch(f"{_UTIL}.close_old_connections"), patch(f"{_UTIL}.time.sleep"):
            with pytest.raises(OperationalError, match="query_wait_timeout"):
                retry_on_db_pool_timeout(operation, MagicMock(), max_attempts=3)
        assert operation.call_count == 3

    def test_reraises_non_pool_operational_error_immediately(self) -> None:
        # A genuine query error must not be mistaken for transient pool pressure and retried.
        operation = MagicMock(side_effect=OperationalError('column "foo" does not exist'))
        with patch(f"{_UTIL}.close_old_connections") as close, patch(f"{_UTIL}.time.sleep"):
            with pytest.raises(OperationalError, match="does not exist"):
                retry_on_db_pool_timeout(operation, MagicMock())
        assert operation.call_count == 1
        close.assert_not_called()
