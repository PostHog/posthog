from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.feature_flags.backend.api.request_usage import (
    REQUEST_USAGE_QUERY_SETTINGS,
    FeatureFlagRequestUsageQuerySerializer,
    aggregate_feature_flag_request_usage,
    get_feature_flag_request_usage,
)


class TestFeatureFlagRequestUsage(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        feature_flag_patcher = patch(
            "products.feature_flags.backend.api.request_usage.feature_enabled_or_false", return_value=True
        )
        feature_flag_patcher.start()
        self.addCleanup(feature_flag_patcher.stop)

    @parameterized.expand(
        [
            ("hour", "2026-08-01T00:00:00Z", "2026-08-09T00:00:01Z"),
            ("day", "2026-07-01T00:00:00Z", "2026-08-02T00:00:01Z"),
        ]
    )
    def test_rejects_ranges_that_exceed_the_interval_limit(self, interval: str, date_from: str, date_to: str) -> None:
        serializer = FeatureFlagRequestUsageQuerySerializer(
            data={"time_interval": interval, "date_from": date_from, "date_to": date_to}
        )

        assert not serializer.is_valid()
        assert "non_field_errors" in serializer.errors

    def test_accepts_hourly_range_from_last_seven_days_preset(self) -> None:
        serializer = FeatureFlagRequestUsageQuerySerializer(
            data={
                "time_interval": "hour",
                "date_from": "2026-08-01T00:00:00Z",
                "date_to": "2026-08-08T23:59:59Z",
            }
        )

        assert serializer.is_valid(), serializer.errors

    @patch("products.feature_flags.backend.api.request_usage.get_feature_flag_request_usage")
    def test_returns_usage_for_the_project_in_the_url(self, mock_get_usage) -> None:
        mock_get_usage.return_value = [
            {
                "bucket": datetime(2026, 8, 20, tzinfo=UTC),
                "request_type": "local_evaluation",
                "sdk": "posthog-ruby",
                "request_count": 12,
                "billing_units": 120,
            }
        ]

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flag_request_usage/",
            {
                "date_from": "2026-08-20T00:00:00Z",
                "date_to": "2026-08-21T00:00:00Z",
                "time_interval": "hour",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0] == {
            "bucket": "2026-08-20T00:00:00Z",
            "request_type": "local_evaluation",
            "sdk": "posthog-ruby",
            "request_count": 12,
            "billing_units": 120,
        }
        assert mock_get_usage.call_args.kwargs["team_id"] == self.team.id

    def test_returns_not_found_when_request_usage_flag_is_disabled(self) -> None:
        with patch("products.feature_flags.backend.api.request_usage.feature_enabled_or_false", return_value=False):
            response = self.client.get(
                f"/api/projects/{self.team.id}/feature_flag_request_usage/",
                {
                    "date_from": "2026-08-20T00:00:00Z",
                    "date_to": "2026-08-21T00:00:00Z",
                    "time_interval": "hour",
                },
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("missing breakdown", "", [("other", 10)]),
            ("partial breakdown", '{"posthog-node": 4}', [("other", 6), ("posthog-node", 4)]),
        ]
    )
    def test_attributes_unclassified_billed_requests_to_other(
        self, _name: str, sdk_breakdown: str, expected: list[tuple[str, int]]
    ) -> None:
        bucket = datetime(2026, 8, 20, tzinfo=UTC)

        results = aggregate_feature_flag_request_usage([(bucket, "remote_evaluation", 10, sdk_breakdown)])

        assert [(result["sdk"], result["request_count"]) for result in results] == expected

    @patch("products.feature_flags.backend.api.request_usage.sync_execute")
    def test_clickhouse_query_is_scoped_and_weights_local_requests(self, mock_sync_execute) -> None:
        bucket = datetime(2026, 8, 20, tzinfo=UTC)
        mock_sync_execute.return_value = [(bucket, "local_evaluation", 4, '{"posthog-node": 4}')]

        results = get_feature_flag_request_usage(
            team_id=self.team.id,
            date_from=datetime(2026, 8, 20, tzinfo=UTC),
            date_to=datetime(2026, 8, 21, tzinfo=UTC),
            time_interval="day",
        )

        query, params = mock_sync_execute.call_args.args[:2]
        assert "distinct_id = toString(%(team_id)s)" in query
        assert params["team_id"] == self.team.id
        assert mock_sync_execute.call_args.kwargs["team_id"] == self.team.id
        assert mock_sync_execute.call_args.kwargs["settings"] == REQUEST_USAGE_QUERY_SETTINGS
        assert results[0]["request_count"] == 4
        assert results[0]["billing_units"] == 40
