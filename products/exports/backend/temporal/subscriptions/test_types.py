from parameterized import parameterized

from products.exports.backend.temporal.subscriptions.types import DeliveryStatus, GenerateAIReportResult


class TestGenerateAIReportResult:
    # all_queries_failed is the single source of truth for the workflow's FAILED-vs-COMPLETED decision,
    # so a regression here (dropping the zero-steps guard, or flipping >= ) would silently mislabel a
    # fully-degraded report as completed.
    @parameterized.expand(
        [
            ("no_steps_aborted_or_skipped", 0, 0, False),
            ("partial_failure", 1, 2, False),
            ("all_failed", 2, 2, True),
            ("single_step_failed", 1, 1, True),
        ]
    )
    def test_all_queries_failed(self, _name, failed: int, total: int, expected: bool) -> None:
        result = GenerateAIReportResult(failed_step_count=failed, total_step_count=total)
        assert result.all_queries_failed is expected

    # failure_error builds the access-safe reason recorded on a fully-degraded delivery's error column.
    # A regression that dropped the singular/plural subject or the error-type detail — or interpolated
    # raw query content instead of the class-name strings — would surface as a message mismatch here.
    @parameterized.expand(
        [
            (
                "single_no_types",
                1,
                [],
                "The query the AI generated failed to run, so the report could not be computed.",
            ),
            (
                "multiple_no_types",
                3,
                [],
                "All 3 queries the AI generated failed to run, so the report could not be computed.",
            ),
            (
                "single_with_type",
                1,
                ["ExposedHogQLError"],
                "The query the AI generated failed to run (ExposedHogQLError), so the report could not be computed.",
            ),
            (
                "multiple_with_types",
                2,
                ["ExposedHogQLError", "ResolutionError"],
                "All 2 queries the AI generated failed to run (ExposedHogQLError, ResolutionError), so the report could not be computed.",
            ),
        ]
    )
    def test_failure_error(self, _name, total: int, error_types: list[str], expected_message: str) -> None:
        result = GenerateAIReportResult(failed_step_count=total, total_step_count=total, query_error_types=error_types)
        assert result.failure_error() == {"message": expected_message, "type": "AIReportQueryFailure"}

    # delivered_status maps a shipped report to the status the workflow records: fully degraded (every query
    # failed) → FAILED with the failure detail attached; partial or clean → COMPLETED with no generation
    # error. Guards the workflow's FAILED-vs-COMPLETED wiring against a dropped check or a flipped comparison.
    @parameterized.expand(
        [
            ("all_failed", 2, 2, DeliveryStatus.FAILED, True),
            ("single_step_failed", 1, 1, DeliveryStatus.FAILED, True),
            ("partial_stays_completed", 1, 2, DeliveryStatus.COMPLETED, False),
            ("no_steps_stays_completed", 0, 0, DeliveryStatus.COMPLETED, False),
        ]
    )
    def test_delivered_status(self, _name, failed: int, total: int, expected_status: str, expects_error: bool) -> None:
        result = GenerateAIReportResult(failed_step_count=failed, total_step_count=total)
        status, error = result.delivered_status()
        assert status == expected_status
        assert error == (result.failure_error() if expects_error else None)
