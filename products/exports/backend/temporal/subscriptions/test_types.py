from parameterized import parameterized

from products.exports.backend.temporal.subscriptions.types import GenerateAIReportResult


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
