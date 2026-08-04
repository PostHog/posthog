from django.db import OperationalError

from parameterized import parameterized

from products.replay_vision.backend.temporal.db_errors import is_transient_db_error


class TestIsTransientDbError:
    @parameterized.expand(
        [
            ("query_wait_timeout", "query_wait_timeout"),
            ("dropped_connection", "server closed the connection unexpectedly"),
            ("connection_failed", "connection failed: timeout expired"),
        ]
    )
    def test_recognizes_transient_pool_markers(self, _name: str, message: str) -> None:
        assert is_transient_db_error(OperationalError(message)) is True

    def test_other_operational_errors_are_not_transient(self) -> None:
        # A real query bug (e.g. a bad column reference) must not be retried as if it were a pool blip.
        assert is_transient_db_error(OperationalError('relation "missing_table" does not exist')) is False

    def test_non_operational_errors_are_not_transient(self) -> None:
        # Only OperationalError carries pool-pressure semantics; a coincidental substring match on an
        # unrelated exception type must not be treated as retryable/non-reportable.
        assert is_transient_db_error(ValueError("query_wait_timeout")) is False
