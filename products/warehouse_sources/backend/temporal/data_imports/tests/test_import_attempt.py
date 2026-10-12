from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports import import_attempt


class TestFailedImportAttempts:
    @parameterized.expand(
        [
            ("first_attempt", 0, 0, 1, 0),
            ("temporal_retries", 0, 0, 3, 2),
            ("clean_handoffs_do_not_count", 2, 2, 1, 0),
            ("failures_before_a_handoff_still_count", 3, 1, 1, 2),
            ("failures_on_both_sides_of_a_handoff", 3, 1, 2, 3),
        ]
    )
    def test_counts_failures_across_executions(self, _name, prior_attempts, handoffs, temporal_attempt, expected):
        import_attempt.set_attempts_before_this_execution(prior_attempts, handoffs=handoffs)
        try:
            with mock.patch.object(import_attempt, "current_activity_attempt", return_value=temporal_attempt):
                assert import_attempt.failed_import_attempts() == expected
        finally:
            import_attempt.set_attempts_before_this_execution(0)
