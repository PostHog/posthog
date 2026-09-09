from django.test import SimpleTestCase

from clickhouse_driver.errors import NetworkError, ServerException, SocketTimeoutError
from parameterized import parameterized

from posthog.errors import wrap_clickhouse_query_error

from products.logs.backend.logs_availability import LogsNotAvailable, LogsWorkloadUnreachable, logs_unavailable_reason


def _clickhouse_error(code: int) -> Exception:
    return wrap_clickhouse_query_error(ServerException("something went wrong", code=code))


class TestLogsAvailability(SimpleTestCase):
    @parameterized.expand(
        [
            ("unknown_table", _clickhouse_error(60), LogsNotAvailable),
            # UNKNOWN_DATABASE has no named exception class, so it has to match by code.
            ("unknown_database", _clickhouse_error(81), LogsNotAvailable),
            ("unreachable_host", NetworkError("Connection refused"), LogsWorkloadUnreachable),
            ("connect_timeout", SocketTimeoutError("timed out"), LogsWorkloadUnreachable),
            # A real defect must keep reaching the 500 handler rather than read as "not set up".
            ("too_many_rows", _clickhouse_error(241), None),
            ("unrelated_error", ValueError("boom"), None),
        ]
    )
    def test_classifies_error(self, _name, error, expected):
        self.assertIs(logs_unavailable_reason(error), expected)

    def test_unreachable_workload_stays_a_retryable_5xx(self):
        # A transient cluster blip must not read as "logs are not set up", which would drop it out
        # of 5xx alerting and out of every caller's retry path.
        self.assertEqual(LogsWorkloadUnreachable.status_code, 503)
        self.assertEqual(LogsNotAvailable.status_code, 400)
