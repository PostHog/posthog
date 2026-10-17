from datetime import UTC, datetime

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.constants import FlagRequestType

from products.feature_flags.backend.usage_comparison import compare_flag_usage_windows


@override_settings(DECIDE_BILLING_ANALYTICS_TOKEN="test-token")
class TestFlagUsageComparison(SimpleTestCase):
    @parameterized.expand(
        [
            (FlagRequestType.DECIDE, "feature_flag_requests"),
            (FlagRequestType.LOCAL_EVALUATION, "feature_flag_local_evaluation_requests"),
        ]
    )
    def test_matches_source_buckets_when_export_crosses_midnight(self, request_type: FlagRequestType, key: str) -> None:
        export_day = datetime(2026, 6, 2, tzinfo=UTC)
        start = datetime(2026, 6, 1, 23, 58, tzinfo=UTC)
        with patch(
            "products.feature_flags.backend.usage_comparison.sync_execute",
            side_effect=[
                [("batch-id", export_day, 13, int(start.timestamp()), int(export_day.timestamp()))],
                [(12, 0)],
            ],
        ) as execute:
            rows = compare_flag_usage_windows(team_id=123, export_day=export_day, request_type=request_type)
        assert rows[0].source_start == start
        assert rows[0].source_end == datetime(2026, 6, 2, 0, 2, tzinfo=UTC)
        assert (rows[0].legacy, rows[0].realtime) == (13, 12)
        assert execute.call_args.args[1] == {
            "team_id": 123,
            "usage_key": key,
            "begin": start,
            "end": rows[0].source_end,
        }

    @parameterized.expand([(0, 120), (200, 100), (120, 8 * 86400)])
    def test_rejects_invalid_or_unbounded_source_windows_before_scanning_records(self, begin: int, end: int) -> None:
        day = datetime(2026, 6, 2, tzinfo=UTC)
        with patch(
            "products.feature_flags.backend.usage_comparison.sync_execute",
            return_value=[("batch-id", day, 1, begin, end)],
        ) as execute:
            with self.assertRaises(ValueError):
                compare_flag_usage_windows(team_id=123, export_day=day, request_type=FlagRequestType.DECIDE)
        execute.assert_called_once()
